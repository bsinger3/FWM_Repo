#!/usr/bin/env node
/**
 * Manual DATA-ENTRY dashboard for the handful of Amazon product pages we could
 * NOT fetch because Amazon soft-blocked them. There is no title/breadcrumb for
 * these rows (the fetch never succeeded), so a human must open each listing in
 * the browser and TYPE the data in.
 *
 * Input  : FWM_Data/_reports/residual_taxonomy/blocked_rows.ndjson
 *          { product_page_id, asin, canonical_url, normalized_product_page_url }
 *
 * Output : saved straight into the repo (no browser download), into the same
 *          gitignored dir the amazon-taxonomy-manual-review dashboard uses:
 *          data-pipelines/products/manual_taxonomy_review/blocked_manual_entries.json
 *
 * Mirrors tools/amazon-taxonomy-manual-review/server.mjs: vanilla node:http,
 * taxonomy dropdowns sourced from clothing-taxonomy.json, debounced autosave.
 *
 * Usage:  node tools/amazon-blocked-manual-entry/server.mjs
 *         PORT=4177 node tools/amazon-blocked-manual-entry/server.mjs
 */

import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = Number(process.env.PORT) || 4177;
const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
const blockedRowsPath = path.join(reportsDir, "residual_taxonomy", "blocked_rows.ndjson");
const taxonomyPath = path.join(repoRoot, "data-pipelines/products/taxonomy/clothing-taxonomy.json");
const outputDir = path.join(repoRoot, "data-pipelines/products/manual_taxonomy_review");
const outputJson = path.join(outputDir, "blocked_manual_entries.json");

// ---- data loading -----------------------------------------------------------

async function loadBlockedRows() {
  const raw = await readFile(blockedRowsPath, "utf8");
  const rows = [];
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    let r;
    try {
      r = JSON.parse(line);
    } catch {
      continue;
    }
    if (!r.product_page_id) continue;
    rows.push({
      product_page_id: r.product_page_id,
      asin: r.asin,
      canonical_url: r.canonical_url,
      normalized_product_page_url: r.normalized_product_page_url,
    });
  }
  return rows;
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
      const rows = await loadBlockedRows();
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
      entries[body.product_page_id] = {
        product_page_id: body.product_page_id,
        asin: body.asin || null,
        canonical_url: body.canonical_url || null,
        title: body.title || "",
        breadcrumb: body.breadcrumb || "",
        mother_category_id: body.mother_category_id || null,
        clothing_type_ids: Array.isArray(body.clothing_type_ids) ? body.clothing_type_ids : [],
        notes: body.notes || "",
        is_404: Boolean(body.is_404),
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
  console.log(`Amazon blocked manual-entry dashboard: http://localhost:${PORT}`);
  console.log(`Reading blocked rows from ${path.relative(repoRoot, blockedRowsPath)}`);
  console.log(`Saving entries into the repo: ${path.relative(repoRoot, outputJson)}`);
});
