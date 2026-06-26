#!/usr/bin/env node
// Fold Codex's scraped results (codex-uncategorized-product-pages.result.ndjson)
// into the dashboard's decisions.json:
//   - not_clothing=true            -> a "remove" decision (dead/non-apparel page)
//   - otherwise                    -> a "recategorize" decision carrying the
//                                     scraped product_title (-> product_title_raw)
//
// Existing decisions are preserved; a Codex row whose id ALREADY has a human
// decision is skipped (your dashboard choices win). No DB writes — this only
// updates decisions.json, which the apply script consumes later.
//
//   node tools/other-category-approval/merge-codex-results.mjs

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const resultPath = path.join(toolDir, "codex-uncategorized-product-pages.result.ndjson");
const decisionsPath = path.join(toolDir, "data", "decisions.json");
const datasetPath = path.join(toolDir, "data", "other-category-dataset.json");

const VALID = new Set([
  "accessories", "activewear", "bodysuits", "bottoms", "dresses", "intimates",
  "jumpsuits", "outerwear", "sets", "swimwear", "tops",
]);

const rows = readFileSync(resultPath, "utf8").split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));
const decisions = existsSync(decisionsPath) ? JSON.parse(readFileSync(decisionsPath, "utf8")) : {};
const dataset = JSON.parse(readFileSync(datasetPath, "utf8"));
const otherIds = new Set(dataset.items.map((i) => i.product_page_id)); // rows still in 'other'

const now = new Date().toISOString();
let recat = 0;
let remove = 0;
const skipped = [];
const rejected = [];

for (const r of rows) {
  const id = r.product_page_id;
  if (!id || !otherIds.has(id)) { rejected.push({ id, why: "not an 'other' row in current dataset" }); continue; }
  if (decisions[id]) { skipped.push({ id, why: `already has a ${decisions[id].decision} decision` }); continue; }

  if (r.not_clothing === true) {
    decisions[id] = { product_page_id: id, decision: "remove", removed_at: now, source: "codex", reason: r.evidence || "not_clothing" };
    remove += 1;
    continue;
  }
  const cat = r.suggested_mother_category;
  if (!cat || cat === "other" || (!r.is_new_category && !VALID.has(cat))) {
    rejected.push({ id, why: `unusable category "${cat}"` });
    continue;
  }
  decisions[id] = {
    product_page_id: id,
    decision: "recategorize",
    chosen_mother_category_id: cat,
    chosen_mother_category_label: cat,
    is_new_category: Boolean(r.is_new_category),
    clothing_type_id: null, // Codex's observed_item_type is free-text; leave the controlled array as-is
    new_product_title: typeof r.product_title === "string" && r.product_title.trim() ? r.product_title.trim() : null,
    approved_at: now,
    source: "codex",
    confidence: r.confidence || null,
    evidence: r.evidence || null,
  };
  recat += 1;
}

writeFileSync(decisionsPath, JSON.stringify(decisions, null, 2) + "\n");

console.log(`Folded Codex results into ${path.relative(path.resolve(toolDir, "..", ".."), decisionsPath)}`);
console.log(`  added recategorize: ${recat}`);
console.log(`  added remove:       ${remove}`);
console.log(`  skipped (already decided by hand): ${skipped.length}`);
console.log(`  rejected (bad data): ${rejected.length}`);
if (skipped.length) for (const s of skipped) console.log(`    skip ${s.id} — ${s.why}`);
if (rejected.length) for (const s of rejected) console.log(`    reject ${s.id} — ${s.why}`);
console.log(`  total decisions now: ${Object.keys(decisions).length}`);
