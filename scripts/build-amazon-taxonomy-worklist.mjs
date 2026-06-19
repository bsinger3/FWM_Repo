#!/usr/bin/env node
/**
 * STEP 0 of the FREE Amazon taxonomy backfill.
 *
 * Build the work-list of Amazon product pages that still have NO category, so a
 * later fetch loop can iterate over a stable, resumable file instead of querying
 * the DB on every run.
 *
 * Input:  data-pipelines/products/product_pages_working_copy.ndjson
 *         (regenerate first with: node scripts/export-product-pages-working-copy.mjs)
 *
 * Filter: normalized_product_page_url matches /amazon\./i
 *         AND mother_category_id is empty (taxonomy_status missing or
 *         proposed_pending_review with no usable category).
 *         A valid 10-char ASIN must be extractable from the URL; rows without
 *         one are dropped (and counted).
 *
 * Output: FWM_Data/_reports/amazon_taxonomy_worklist_<timestamp>.ndjson
 *         one object per page:
 *           { product_page_id, normalized_product_page_url, asin,
 *             canonical_url: "https://www.amazon.com/dp/{asin}" }
 *
 * Read-only. Writes one NDJSON file under FWM_Data/_reports and prints the count.
 *
 * Usage:
 *   node scripts/build-amazon-taxonomy-worklist.mjs
 *   node scripts/build-amazon-taxonomy-worklist.mjs --working-copy=path/to.ndjson
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArg(name, fallback = "") {
  const prefix = `--${name}=`;
  const hit = process.argv.find((arg) => arg.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}

const AMAZON_RE = /amazon\./i;
const ASIN_RE = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?#]|$)/i;

function extractAsin(url) {
  const match = String(url || "").match(ASIN_RE);
  return match ? match[1].toUpperCase() : null;
}

function timestampForFilename() {
  // Use the working copy's mtime is unnecessary; the runtime forbids Date.now()
  // in workflow scripts but this is a plain CLI — a wall-clock stamp is fine here.
  return new Date().toISOString().replace(/[:.]/g, "").replace(/-/g, "");
}

async function main() {
  const workingCopyPath = path.resolve(
    repoRoot,
    parseArg("working-copy", "data-pipelines/products/product_pages_working_copy.ndjson"),
  );
  if (!existsSync(workingCopyPath)) {
    throw new Error(
      `Working copy not found: ${workingCopyPath}\n` +
        `Regenerate it first: node scripts/export-product-pages-working-copy.mjs`,
    );
  }

  const raw = await readFile(workingCopyPath, "utf8");
  const lines = raw.split("\n").filter((line) => line.trim());

  let amazonRows = 0;
  let amazonMissingCategory = 0;
  let droppedNoAsin = 0;
  const seenAsin = new Set();
  const worklist = [];

  for (const line of lines) {
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      continue;
    }
    const url = row.normalized_product_page_url || "";
    if (!AMAZON_RE.test(url)) continue;
    amazonRows += 1;

    // "no category" = mother_category_id empty (covers missing + proposed-pending
    // with no usable category, since the working copy leaves it blank in both).
    if (String(row.mother_category_id || "").trim() !== "") continue;
    amazonMissingCategory += 1;

    const asin = extractAsin(url);
    if (!asin) {
      droppedNoAsin += 1;
      continue;
    }

    worklist.push({
      product_page_id: row.id,
      normalized_product_page_url: url,
      asin,
      canonical_url: `https://www.amazon.com/dp/${asin}`,
    });
    seenAsin.add(asin);
  }

  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const outPath = path.join(reportsDir, `amazon_taxonomy_worklist_${timestampForFilename()}.ndjson`);
  await writeFile(outPath, worklist.map((r) => JSON.stringify(r)).join("\n") + "\n", "utf8");

  console.log(`Working copy:            ${workingCopyPath}`);
  console.log(`Amazon rows (any):       ${amazonRows}`);
  console.log(`Amazon, no category:     ${amazonMissingCategory}`);
  console.log(`Dropped (no valid ASIN): ${droppedNoAsin}`);
  console.log(`Unique ASINs:            ${seenAsin.size}`);
  console.log(`Work-list rows written:  ${worklist.length}`);
  console.log(`Wrote work-list -> ${outPath}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
