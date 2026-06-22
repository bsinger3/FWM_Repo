#!/usr/bin/env node
/**
 * Build a local "working copy" of everything we eventually want to land in the
 * Supabase `product_pages` table, carrying the MOST UP-TO-DATE taxonomy we have.
 *
 * Why a merge is needed: the dev `staging.product_pages` table holds the full
 * row set but its taxonomy columns are mostly empty — the freshly collected
 * taxonomy lives (unpromoted) in the `proposed` field of the taxonomy audit
 * reports under FWM_Data/_reports/. This script joins the two:
 *
 *   final taxonomy = promoted DB value if present, else latest audit proposal
 *
 * Each row is tagged with `taxonomy_status` (promoted | proposed_pending_review
 * | missing) and `taxonomy_source` (db | audit_proposal | none) so the
 * provenance is explicit and a later promote step can act on it.
 *
 * Read-only: it SELECTs from the dev DB and reads local report JSON. It writes
 * nothing back to Supabase.
 *
 * Usage:
 *   node scripts/export-product-pages-working-copy.mjs
 *   node scripts/export-product-pages-working-copy.mjs --out=data-pipelines/products/product_pages_working_copy.csv
 *   node scripts/export-product-pages-working-copy.mjs --format=ndjson
 *   node scripts/export-product-pages-working-copy.mjs --format=both   (default)
 */

import { execFileSync } from "node:child_process";
import { readdir, readFile, writeFile, mkdir, stat } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArg(name, fallback = "") {
  const prefix = `--${name}=`;
  const found = process.argv.find((a) => a.startsWith(prefix));
  return found ? found.slice(prefix.length) : fallback;
}

// --- tiny .env loader (only fills values not already in the environment) ---
function loadDotEnv() {
  const envPath = path.join(repoRoot, ".env");
  if (!existsSync(envPath)) return;
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
    if (!m) continue;
    const key = m[1];
    let val = m[2];
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = val;
  }
}

loadDotEnv();

const databaseUrl = process.env.DEV_DATABASE_URL;
if (!databaseUrl) {
  console.error("DEV_DATABASE_URL is not set (looked in environment and .env).");
  process.exit(1);
}
if (process.env.PROD_DATABASE_URL && databaseUrl === process.env.PROD_DATABASE_URL) {
  console.error("Refusing to run: DEV_DATABASE_URL equals PROD_DATABASE_URL.");
  process.exit(1);
}

const format = (parseArg("format", "both") || "both").toLowerCase();
const defaultOut = path.join(repoRoot, "data-pipelines", "products", "product_pages_working_copy.csv");
const outCsv = parseArg("out", defaultOut);
const outBase = outCsv.replace(/\.csv$/i, "");
const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");

// ---------------------------------------------------------------------------
// 1) Pull the base rows from staging.product_pages (one JSON object per line).
// ---------------------------------------------------------------------------
function queryProductPages() {
  const psql = postgresClientTool("psql");
  const { args, env } = postgresConnectionArgs(databaseUrl);
  const sql = `
    select row_to_json(t) from (
      select
        id,
        normalized_product_page_url,
        source_site,
        brand,
        product_title_raw,
        product_category_raw,
        mother_category_id,
        category_confidence,
        category_evidence,
        category_source_field,
        category_breadcrumb_path,
        category_extractor_version,
        category_checked_at,
        observed_clothing_type_ids,
        needs_manual_review,
        image_row_count,
        source_status,
        robots_disallowed,
        first_seen_at,
        last_seen_at,
        updated_at
      from staging.product_pages
    ) t;`;
  const stdout = execFileSync(
    psql,
    [...args, "--no-align", "--tuples-only", "--quiet", "--command", sql],
    { env: { ...process.env, ...env }, encoding: "utf8", maxBuffer: 1024 * 1024 * 512 },
  );
  return stdout
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));
}

// ---------------------------------------------------------------------------
// 2) Read all taxonomy audit reports; keep the latest proposal per page.
//    (Same dedup approach as export-missing-taxonomy-primary-ids.mjs.)
// ---------------------------------------------------------------------------
function proposedPrimaryId(row) {
  return String(
    row?.proposed?.primaryCategory?.mother_category_id
      || row?.proposed?.primary_category?.mother_category_id
      || row?.proposed?.primaryCategory?.motherCategoryId
      || "",
  ).trim();
}

function proposedPrimary(row) {
  const p = row?.proposed?.primaryCategory || row?.proposed?.primary_category || null;
  if (!p) return null;
  return {
    mother_category_id: proposedPrimaryId(row),
    category_confidence: String(p.category_confidence || p.confidence || "").trim(),
    category_evidence: String(p.category_evidence || p.evidence || "").trim(),
    category_source_field: String(p.category_source_field || p.source_field || "").trim(),
  };
}

function proposedItemTagIds(row) {
  const tags = row?.proposed?.itemTags || row?.proposed?.item_tags || [];
  if (!Array.isArray(tags)) return [];
  return [...new Set(tags.map((t) => String(t?.clothing_type_id || "").trim()).filter(Boolean))];
}

function rowProductPageId(row) {
  return String(row?.product_page_id || row?.productPageId || row?.product_page?.id || "").trim();
}

async function readLatestProposals() {
  if (!existsSync(reportsDir)) {
    console.warn(`No reports dir at ${reportsDir} — proposals will be empty.`);
    return new Map();
  }
  const names = (await readdir(reportsDir))
    .filter((n) => /^dev_product_page_taxonomy_audit_.*\.json$/.test(n))
    .sort();
  const latest = new Map();
  for (const name of names) {
    const p = path.join(reportsDir, name);
    let report;
    try {
      report = JSON.parse(await readFile(p, "utf8"));
    } catch {
      continue;
    }
    const generatedAt = report.generated_at || report.generatedAt || (await stat(p)).mtime.toISOString();
    const results = Array.isArray(report.results) ? report.results : [];
    for (const r of results) {
      const id = rowProductPageId(r);
      if (!id) continue;
      const prev = latest.get(id);
      if (!prev || String(generatedAt).localeCompare(String(prev.generatedAt)) >= 0) {
        latest.set(id, {
          generatedAt,
          extractorVersion: report.extractor_version || report.extractorVersion || "",
          primary: proposedPrimary(r),
          itemTagIds: proposedItemTagIds(r),
          skipReason: String(r?.skip_reason || r?.skipReason || "").trim(),
        });
      }
    }
  }
  return latest;
}

// ---------------------------------------------------------------------------
// 3) Merge + serialize.
// ---------------------------------------------------------------------------
const COLUMNS = [
  "id",
  "normalized_product_page_url",
  "source_site",
  "brand",
  "product_title_raw",
  "product_category_raw",
  // merged "final" taxonomy view
  "mother_category_id",
  "category_confidence",
  "category_evidence",
  "category_source_field",
  "clothing_type_ids",
  "taxonomy_status",
  "taxonomy_source",
  // provenance
  "db_mother_category_id",
  "proposed_mother_category_id",
  "proposed_extractor_version",
  "audit_generated_at",
  "audit_skip_reason",
  // page metadata
  "needs_manual_review",
  "image_row_count",
  "source_status",
  "robots_disallowed",
  "last_seen_at",
  "updated_at",
];

function joinArr(v) {
  if (Array.isArray(v)) return v.filter(Boolean).join("|");
  return v == null ? "" : String(v);
}

function buildRecord(db, proposal) {
  const dbCat = String(db.mother_category_id || "").trim();
  const propCat = proposal?.primary?.mother_category_id || "";
  let status = "missing";
  let source = "none";
  let finalCat = "";
  let finalConf = "";
  let finalEvidence = "";
  let finalSourceField = "";
  let finalTags = Array.isArray(db.observed_clothing_type_ids) ? db.observed_clothing_type_ids : [];

  if (dbCat) {
    status = "promoted";
    source = "db";
    finalCat = dbCat;
    finalConf = db.category_confidence || "";
    finalEvidence = db.category_evidence || "";
    finalSourceField = db.category_source_field || "";
  } else if (propCat) {
    status = "proposed_pending_review";
    source = "audit_proposal";
    finalCat = propCat;
    finalConf = proposal.primary.category_confidence || "";
    finalEvidence = proposal.primary.category_evidence || "";
    finalSourceField = proposal.primary.category_source_field || "";
    if (proposal.itemTagIds.length) finalTags = proposal.itemTagIds;
  }

  return {
    id: db.id,
    normalized_product_page_url: db.normalized_product_page_url,
    source_site: db.source_site,
    brand: db.brand,
    product_title_raw: db.product_title_raw,
    product_category_raw: db.product_category_raw,
    mother_category_id: finalCat,
    category_confidence: finalConf,
    category_evidence: finalEvidence,
    category_source_field: finalSourceField,
    clothing_type_ids: joinArr(finalTags),
    taxonomy_status: status,
    taxonomy_source: source,
    db_mother_category_id: dbCat,
    proposed_mother_category_id: propCat,
    proposed_extractor_version: proposal?.extractorVersion || "",
    audit_generated_at: proposal?.generatedAt || "",
    audit_skip_reason: proposal?.skipReason || "",
    needs_manual_review: db.needs_manual_review,
    image_row_count: db.image_row_count,
    source_status: db.source_status,
    robots_disallowed: db.robots_disallowed,
    last_seen_at: db.last_seen_at,
    updated_at: db.updated_at,
  };
}

function csvCell(v) {
  if (v == null) return "";
  const s = String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCsv(records) {
  const lines = [COLUMNS.join(",")];
  for (const r of records) lines.push(COLUMNS.map((c) => csvCell(r[c])).join(","));
  return lines.join("\n") + "\n";
}

function toNdjson(records) {
  return records.map((r) => JSON.stringify(r)).join("\n") + "\n";
}

async function main() {
  console.log(`DB: ${redactDatabaseUrl(databaseUrl)}`);
  console.log("Querying staging.product_pages …");
  const dbRows = queryProductPages();
  console.log(`  ${dbRows.length} product pages`);

  console.log(`Reading taxonomy audit proposals from ${reportsDir} …`);
  const proposals = await readLatestProposals();
  console.log(`  ${proposals.size} pages with at least one audit proposal`);

  const records = dbRows
    .map((db) => buildRecord(db, proposals.get(String(db.id))))
    .sort((a, b) => String(a.source_site).localeCompare(String(b.source_site))
      || String(a.normalized_product_page_url).localeCompare(String(b.normalized_product_page_url)));

  const counts = records.reduce((acc, r) => {
    acc[r.taxonomy_status] = (acc[r.taxonomy_status] || 0) + 1;
    return acc;
  }, {});
  const amazonWithTax = records.filter(
    (r) => /amazon\./i.test(r.normalized_product_page_url || "") && r.mother_category_id,
  ).length;

  await mkdir(path.dirname(outCsv), { recursive: true });
  if (format === "csv" || format === "both") {
    await writeFile(outCsv, toCsv(records), "utf8");
    console.log(`Wrote CSV  -> ${outCsv}`);
  }
  if (format === "ndjson" || format === "both") {
    const nd = `${outBase}.ndjson`;
    await writeFile(nd, toNdjson(records), "utf8");
    console.log(`Wrote NDJSON -> ${nd}`);
  }

  console.log("\nTaxonomy status breakdown:");
  for (const [k, v] of Object.entries(counts).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${k.padEnd(24)} ${v}`);
  }
  console.log(`  amazon rows with a (final) category: ${amazonWithTax}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
