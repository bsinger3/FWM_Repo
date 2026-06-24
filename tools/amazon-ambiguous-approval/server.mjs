#!/usr/bin/env node
/**
 * Human APPROVAL dashboard for the 266 Amazon product pages whose taxonomy
 * category was ambiguous (multiple competing signals tied). An LLM already
 * proposed a category for each; this dashboard is for fast human sign-off:
 * approve the proposal as-is, override it, or reject it as not-clothing.
 *
 * Input  : FWM_Data/_reports/residual_taxonomy/ambiguous_rows.ndjson
 *            { product_page_id, asin, canonical_url, title, breadcrumb, bsr,
 *              url_slug, competing_categories:[{mother_category_id, evidence_tag,
 *              source_field}] }
 *          FWM_Data/_reports/residual_taxonomy/ambiguous_decisions_all.ndjson
 *            { product_page_id, asin, mother_category_id, clothing_type_ids:[...],
 *              confidence:"high|medium|low", reasoning }
 *          Joined by product_page_id (1 proposal per row, 266 total).
 *
 * Output : saved straight into the repo (no browser download), into the same
 *          gitignored dir the sibling dashboards use:
 *          data-pipelines/products/manual_taxonomy_review/ambiguous_approvals.json
 *
 * Mirrors tools/amazon-blocked-manual-entry/server.mjs and
 * tools/amazon-taxonomy-manual-review/server.mjs: vanilla node:http, taxonomy
 * dropdowns from clothing-taxonomy.json, debounced autosave into the repo.
 *
 * Usage:  node tools/amazon-ambiguous-approval/server.mjs
 *         PORT=4178 node tools/amazon-ambiguous-approval/server.mjs
 */

import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = Number(process.env.PORT) || 4178;
const reportsDir = path.join(fwmDataDir(repoRoot), "_reports", "residual_taxonomy");
const rowsPath = path.join(reportsDir, "ambiguous_rows.ndjson");
const decisionsPath = path.join(reportsDir, "ambiguous_decisions_all.ndjson");
const taxonomyPath = path.join(repoRoot, "data-pipelines/products/taxonomy/clothing-taxonomy.json");
const outputDir = path.join(repoRoot, "data-pipelines/products/manual_taxonomy_review");
const outputJson = path.join(outputDir, "ambiguous_approvals.json");

// ---- data loading -----------------------------------------------------------

function readNdjson(file) {
  const raw = readFileSync(file, "utf8");
  const out = [];
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    try {
      out.push(JSON.parse(line));
    } catch {
      /* skip malformed line */
    }
  }
  return out;
}

const CONFIDENCE_ORDER = { low: 0, medium: 1, high: 2 };

function loadRows() {
  const rows = readNdjson(rowsPath).filter((r) => r.product_page_id);
  const decisions = {};
  for (const d of readNdjson(decisionsPath)) {
    if (d.product_page_id) decisions[d.product_page_id] = d;
  }
  const joined = rows.map((r) => {
    const d = decisions[r.product_page_id] || {};
    return {
      product_page_id: r.product_page_id,
      asin: r.asin,
      canonical_url: r.canonical_url,
      title: r.title || "",
      breadcrumb: r.breadcrumb || "",
      bsr: r.bsr || "",
      url_slug: r.url_slug || "",
      competing_categories: Array.isArray(r.competing_categories) ? r.competing_categories : [],
      llm_proposal: {
        mother_category_id: d.mother_category_id || null,
        clothing_type_ids: Array.isArray(d.clothing_type_ids) ? d.clothing_type_ids : [],
        confidence: d.confidence || "unknown",
        reasoning: d.reasoning || "",
      },
    };
  });
  // Default sort: lowest confidence first (low, medium, high), stable within.
  joined.sort((a, b) => {
    const ca = CONFIDENCE_ORDER[a.llm_proposal.confidence] ?? 99;
    const cb = CONFIDENCE_ORDER[b.llm_proposal.confidence] ?? 99;
    return ca - cb;
  });
  return joined;
}

function loadTaxonomy() {
  const t = JSON.parse(readFileSync(taxonomyPath, "utf8"));
  const categories = (t.mother_categories || []).map((m) => ({ id: m.id, label: m.label, description: m.description || "" }));
  const tags = (t.category_tags || []).map((c) => ({ id: c.id, mother_category_id: c.mother_category_id }));
  return { categories, tags };
}

async function loadEntries() {
  const map = {};
  if (!existsSync(outputJson)) return map;
  try {
    const parsed = JSON.parse(await readFile(outputJson, "utf8"));
    for (const e of parsed.entries || []) {
      if (e.product_page_id) map[e.product_page_id] = e;
    }
  } catch {
    /* corrupt/empty file — start fresh */
  }
  return map;
}

const entries = await loadEntries();

async function persistEntries() {
  await mkdir(outputDir, { recursive: true });
  const list = Object.values(entries).sort((a, b) => (a.saved_at < b.saved_at ? 1 : -1));
  await writeFile(
    outputJson,
    JSON.stringify({ updated_at: new Date().toISOString(), count: list.length, entries: list }, null, 2) + "\n",
    "utf8",
  );
}

// ---- http -------------------------------------------------------------------

function send(res, status, body, type = "application/json") {
  res.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store" });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return Buffer.concat(chunks).toString("utf8");
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    if (req.method === "GET" && url.pathname === "/") {
      const html = await readFile(path.join(path.dirname(fileURLToPath(import.meta.url)), "public", "index.html"), "utf8");
      return send(res, 200, html, "text/html; charset=utf-8");
    }
    if (req.method === "GET" && url.pathname === "/api/bootstrap") {
      const rows = loadRows();
      const { categories, tags } = loadTaxonomy();
      return send(res, 200, {
        rows,
        categories,
        tags,
        entries,
        total: rows.length,
        saved: rows.filter((r) => entries[r.product_page_id]).length,
        output_path: path.relative(repoRoot, outputJson),
      });
    }
    if (req.method === "POST" && url.pathname === "/api/save") {
      const body = JSON.parse((await readBody(req)) || "{}");
      if (!body.product_page_id) return send(res, 400, { ok: false, error: "missing product_page_id" });
      const decision = ["approved", "overridden", "rejected"].includes(body.decision) ? body.decision : "approved";
      entries[body.product_page_id] = {
        product_page_id: body.product_page_id,
        asin: body.asin || null,
        decision,
        final_mother_category_id: decision === "rejected" ? null : body.final_mother_category_id || null,
        final_clothing_type_ids:
          decision === "rejected" ? [] : Array.isArray(body.final_clothing_type_ids) ? body.final_clothing_type_ids : [],
        llm_proposal: body.llm_proposal || null,
        saved_at: new Date().toISOString(),
      };
      await persistEntries();
      return send(res, 200, { ok: true, saved: Object.keys(entries).length });
    }
    if (req.method === "POST" && url.pathname === "/api/delete") {
      const body = JSON.parse((await readBody(req)) || "{}");
      delete entries[body.product_page_id];
      await persistEntries();
      return send(res, 200, { ok: true, saved: Object.keys(entries).length });
    }
    return send(res, 404, { error: "not found" });
  } catch (error) {
    return send(res, 500, { error: String(error?.message || error) });
  }
});

server.listen(PORT, () => {
  console.log(`Amazon ambiguous approval dashboard: http://localhost:${PORT}`);
  console.log(`Reading rows from ${path.relative(repoRoot, rowsPath)}`);
  console.log(`Reading proposals from ${path.relative(repoRoot, decisionsPath)}`);
  console.log(`Saving approvals into the repo: ${path.relative(repoRoot, outputJson)}`);
});
