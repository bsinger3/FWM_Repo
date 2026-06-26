#!/usr/bin/env node
// Reclassify staging.product_pages rows currently bucketed as mother_category_id='other'
// by running their URL slug (+ any product_title_raw / product_category_raw) through the
// project's canonical extractTaxonomy() rules. Deterministic, no web fetches.
//
// Dry-run by default. Writes require --apply AND FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev.

import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";
import { extractTaxonomy, stripTags } from "./audit-dev-product-page-taxonomy.mjs";

const apply = process.argv.includes("--apply");

// Mother-category ids that extractTaxonomy can emit but that are NOT valid FK
// targets in staging.clothing_mother_categories — fold them onto a valid parent.
const MOTHER_FOLD = new Map([["romper", "jumpsuits"]]);

const VALID_MOTHER = new Set([
  "accessories", "activewear", "bodysuits", "bottoms", "dresses", "intimates",
  "jumpsuits", "other", "outerwear", "sets", "shoes", "swimwear", "tops",
]);

function runPsql(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...connection.env }, maxBuffer: 1024 * 1024 * 100 },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

function urlSlug(url) {
  try {
    const parsed = new URL(url);
    return stripTags(
      decodeURIComponent(parsed.pathname)
        .replace(/[-_/]+/g, " ")
        // Strip CMS dedup digit suffixes glued to a word (e.g. "jeans2", "shortalls4")
        // so the canonical word-boundary phrase rules can still match the garment word.
        .replace(/([a-z])\d+(?=\s|$)/gi, "$1"),
    );
  } catch {
    return "";
  }
}

function fieldsForRow(row) {
  return {
    title: stripTags(row.product_title_raw || ""),
    json_ld_product_core: "",
    breadcrumb: "",
    url_slug: urlSlug(row.normalized_product_page_url),
    json_ld_product_description: "",
    description: "",
    workbook_fallback: stripTags(
      [row.product_category_raw, ...(row.observed_clothing_type_ids || []).filter((t) => t !== "other")]
        .filter(Boolean)
        .join(" "),
    ),
  };
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlTextArray(values) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  if (!items.length) return "array[]::text[]";
  return `array[${items.map(sqlString).join(",")}]::text[]`;
}

async function main() {
  const guard = await assertApprovedDevSupabase();
  printGuardSummary(guard, { prefix: "reclassify-other-categories" });
  const databaseUrl = process.env.DEV_DATABASE_URL;
  assertApprovedDevDatabaseUrl(databaseUrl);

  const rows = JSON.parse(
    runPsql(
      databaseUrl,
      `select coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb) from (
         select id::text, normalized_product_page_url, source_site,
                product_title_raw, product_category_raw, observed_clothing_type_ids
         from staging.product_pages
         where mother_category_id = 'other'
       ) t;`,
    ).trim() || "[]",
  );

  const resolved = [];
  const unresolved = [];
  for (const row of rows) {
    const fields = fieldsForRow(row);
    const taxonomy = extractTaxonomy(fields);
    const primary = taxonomy.primaryCategory;
    let mother = primary?.mother_category_id || null;
    if (mother && MOTHER_FOLD.has(mother)) mother = MOTHER_FOLD.get(mother);
    if (!mother || mother === "other" || !VALID_MOTHER.has(mother)) {
      unresolved.push({ ...row, reason: mother === "other" ? "still_other" : "no_confident_category" });
      continue;
    }
    const itemTag = (taxonomy.itemTags || [])[0];
    resolved.push({
      id: row.id,
      url: row.normalized_product_page_url,
      source_site: row.source_site,
      old_mother: "other",
      new_mother: mother,
      confidence: primary.category_confidence,
      source_field: primary.category_source_field,
      evidence: String(primary.category_evidence || "").slice(0, 160),
      new_clothing_type_id: itemTag?.clothing_type_id || null,
    });
  }

  // Summaries
  const byNew = {};
  const byConf = {};
  const bySource = {};
  for (const r of resolved) {
    byNew[r.new_mother] = (byNew[r.new_mother] || 0) + 1;
    byConf[r.confidence] = (byConf[r.confidence] || 0) + 1;
    bySource[r.source_site] = (bySource[r.source_site] || 0) + 1;
  }
  const unresolvedBySource = {};
  for (const r of unresolved) unresolvedBySource[r.source_site] = (unresolvedBySource[r.source_site] || 0) + 1;

  console.log(`\nTotal 'other' rows: ${rows.length}`);
  console.log(`Reclassifiable: ${resolved.length}`);
  console.log(`Still 'other' (no confident signal): ${unresolved.length}`);
  console.log(`\nProposed new mother categories:`);
  for (const [k, v] of Object.entries(byNew).sort((a, b) => b[1] - a[1])) console.log(`  ${k.padEnd(12)} ${v}`);
  console.log(`\nConfidence of proposals:`);
  for (const [k, v] of Object.entries(byConf).sort((a, b) => b[1] - a[1])) console.log(`  ${k.padEnd(8)} ${v}`);
  console.log(`\nReclassified by source:`);
  for (const [k, v] of Object.entries(bySource).sort((a, b) => b[1] - a[1])) console.log(`  ${String(v).padStart(4)}  ${k}`);
  console.log(`\nStill-'other' by source:`);
  for (const [k, v] of Object.entries(unresolvedBySource).sort((a, b) => b[1] - a[1])) console.log(`  ${String(v).padStart(4)}  ${k}`);

  const reportDir = path.join(fwmDataDir(), "_reports");
  await mkdir(reportDir, { recursive: true });
  const stem = new Date().toISOString().replace(/[-:]/g, "").replace(".", "").slice(0, 15);
  const reportPath = path.join(reportDir, `other_category_reclassification_${stem}.json`);
  await writeFile(reportPath, JSON.stringify({ generated_at: new Date().toISOString(), total: rows.length, resolved, unresolved }, null, 2));
  console.log(`\nProposal written: ${reportPath}`);

  if (!apply) {
    console.log(`\nDRY RUN — no DB writes. Re-run with --apply (and FWM_DEV_DB_WRITE_OK) to apply.`);
    return;
  }

  requireExplicitWriteFlag();
  const EXTRACTOR_VERSION = "other_reclassify_url_slug_v1";

  // Reversible: snapshot the full prior state of every row we are about to touch.
  const beforeIds = resolved.map((r) => sqlString(r.id)).join(",");
  const beforeRows = JSON.parse(
    runPsql(
      databaseUrl,
      `select coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb) from (
         select id::text, mother_category_id, category_confidence, category_evidence,
                category_source_field, category_extractor_version, observed_clothing_type_ids,
                category_checked_at
         from staging.product_pages where id in (${beforeIds})
       ) t;`,
    ).trim() || "[]",
  );
  const snapshotPath = reportPath.replace(/\.json$/, "_before.json");
  await writeFile(snapshotPath, JSON.stringify({ snapshot_at: new Date().toISOString(), rows: beforeRows }, null, 2));
  console.log(`Reversible snapshot written: ${snapshotPath}`);
  // Build a single transactional UPDATE batch.
  const updates = resolved.map((r) => {
    const types = r.new_clothing_type_id ? [r.new_clothing_type_id] : [];
    return `update staging.product_pages set
      mother_category_id = ${sqlString(r.new_mother)},
      category_confidence = ${sqlString(r.confidence)},
      category_evidence = ${sqlString(r.evidence)},
      category_source_field = ${sqlString(r.source_field)},
      category_extractor_version = ${sqlString(EXTRACTOR_VERSION)},
      observed_clothing_type_ids = ${sqlTextArray(types)},
      category_checked_at = now(), updated_at = now()
      where id = ${sqlString(r.id)} and mother_category_id = 'other';`;
  });
  const idList = resolved.map((r) => sqlString(r.id)).join(",");
  const propagate = idList
    ? `update public.images i set mother_category_id = p.mother_category_id
         from staging.product_pages p
         where i.product_page_id = p.id and p.id in (${idList});`
    : "";
  const sql = `begin;\n${updates.join("\n")}\n${propagate}\ncommit;`;
  runPsql(databaseUrl, sql);
  console.log(`\nAPPLIED: reclassified ${resolved.length} product pages (+ propagated mother_category_id to public.images).`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
