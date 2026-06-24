#!/usr/bin/env node
/**
 * Prep inputs for resolving the Amazon backfill's residual rows.
 * Reads the completed progress sidecar (dedup by product_page_id, last line wins)
 * and splits the leftovers into:
 *   - ambiguous_rows.ndjson : fetched OK but no primary category (LLM can deduce from
 *     title/breadcrumb/BSR). Carries the captured text + the tied "competing" cats.
 *   - blocked_rows.ndjson   : captcha_or_block skips (no captured text — need a human
 *     to open the page and type title/breadcrumb).
 *   - taxonomy_vocab.json   : the controlled mother_categories + clothing-type tags.
 *   - ambiguous_chunk_<n>.ndjson : ambiguous rows split into N chunks for parallel LLM.
 * Writes to FWM_Data/_reports/residual_taxonomy/.  Read-only against everything else.
 */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const CHUNKS = Math.max(1, Number(process.argv.find((a) => a.startsWith("--chunks="))?.slice(9)) || 4);

const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
const sidecar = path.join(reportsDir, "amazon_taxonomy_worklist_20260619T182108730Z_progress.ndjson");
const outDir = path.join(reportsDir, "residual_taxonomy");

const byId = new Map();
for (const line of (await readFile(sidecar, "utf8")).trim().split("\n")) {
  try {
    const r = JSON.parse(line);
    if (r.product_page_id) byId.set(r.product_page_id, r);
  } catch {}
}
const rows = [...byId.values()];

const ambiguous = [];
const blocked = [];
for (const r of rows) {
  if (r.skip_reason === "captcha_or_block") {
    blocked.push({
      product_page_id: r.product_page_id,
      asin: r.asin,
      canonical_url: r.canonical_url,
      normalized_product_page_url: r.normalized_product_page_url,
    });
    continue;
  }
  if (!r.skipped && !r.proposed?.primaryCategory?.mother_category_id) {
    const f = r.extracted_fields_preview || {};
    ambiguous.push({
      product_page_id: r.product_page_id,
      asin: r.asin,
      canonical_url: r.canonical_url,
      normalized_product_page_url: r.normalized_product_page_url,
      title: f.title || "",
      breadcrumb: f.breadcrumb || "",
      bsr: f.description || "",
      url_slug: f.url_slug || "",
      competing_categories: (r.proposed?.categoryVotes || [])
        .slice(0, 4)
        .map((v) => ({ mother_category_id: v.mother_category_id, evidence_tag: v.evidence_tag, source_field: v.source_field })),
    });
  }
}

const taxonomy = JSON.parse(await readFile(path.join(repoRoot, "data-pipelines/products/taxonomy/clothing-taxonomy.json"), "utf8"));
const vocab = {
  mother_categories: taxonomy.mother_categories
    .filter((m) => m.id !== "source-review")
    .map((m) => ({ id: m.id, label: m.label, description: m.description })),
  category_tags: (taxonomy.category_tags || []).map((t) => ({ id: t.id, mother_category_id: t.mother_category_id, aliases: t.aliases || [] })),
};

await mkdir(outDir, { recursive: true });
const writeNd = (name, arr) => writeFile(path.join(outDir, name), arr.map((o) => JSON.stringify(o)).join("\n") + "\n", "utf8");

await writeNd("ambiguous_rows.ndjson", ambiguous);
await writeNd("blocked_rows.ndjson", blocked);
await writeFile(path.join(outDir, "taxonomy_vocab.json"), JSON.stringify(vocab, null, 2) + "\n", "utf8");

const perChunk = Math.ceil(ambiguous.length / CHUNKS);
for (let c = 0; c < CHUNKS; c++) {
  await writeNd(`ambiguous_chunk_${c + 1}.ndjson`, ambiguous.slice(c * perChunk, (c + 1) * perChunk));
}

console.log(`out dir:            ${outDir}`);
console.log(`ambiguous rows:     ${ambiguous.length}  -> ${CHUNKS} chunks of ~${perChunk}`);
console.log(`blocked rows:       ${blocked.length}`);
console.log(`vocab mother cats:  ${vocab.mother_categories.length} | tags: ${vocab.category_tags.length}`);
