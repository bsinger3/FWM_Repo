#!/usr/bin/env node
// Generates codex-uncategorized-product-pages.txt — the outsource brief for Codex.
// Scope: the 'other'-bucket product pages that DON'T have a suggested category yet
// (the dashboard's "no suggestion" set). The rows that already have a suggested
// category were human-approved in the dashboard and are NOT included here.
//
// Reads the dashboard dataset (tools/other-category-approval/data/other-category-dataset.json),
// filters items with no suggested_mother_category_id, writes a plain-text prompt +
// annotated link list.
//
//   node tools/other-category-approval/build-codex-uncategorized-list.mjs

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const datasetPath = path.join(toolDir, "data", "other-category-dataset.json");
const decisionsPath = path.join(toolDir, "data", "decisions.json");
const outPath = path.join(toolDir, "codex-uncategorized-product-pages.txt");

const dataset = JSON.parse(readFileSync(datasetPath, "utf8"));
const decisions = existsSync(decisionsPath) ? JSON.parse(readFileSync(decisionsPath, "utf8")) : {};
// Codex handles only rows with NO suggested category AND no human decision yet —
// i.e. the ones still unresolved in the dashboard.
const rows = dataset.items.filter((i) => !i.suggested_mother_category_id && !decisions[i.product_page_id]);

const APPAREL = [
  "activewear", "bodysuits", "bottoms", "dresses", "intimates",
  "jumpsuits", "outerwear", "sets", "swimwear", "tops", "accessories",
];

const L = [];
const rule = "=".repeat(90);
L.push('FWM — Codex task: scrape titles + categories for uncategorized "other" product pages');
L.push("Generated 2026-06-25 · dev DB ref gosqgqpftqlawvnyelkt · staging.product_pages");
L.push(rule);
L.push("");
L.push("CONTEXT");
L.push("-------");
L.push(`The ${rows.length} URLs at the bottom are rows in the Friends With Measurements dev database`);
L.push("(staging.product_pages) currently bucketed as mother_category_id = 'other' that we could NOT");
L.push("auto-suggest a category for — most have no product_title_raw on file (especially the L.L.Bean");
L.push("/llb/shop/<id> links), so there is no signal to categorize them. They are women's clothing");
L.push("product pages. (The other 'other' rows already have a human-approved category and are not here.)");
L.push("");
L.push("YOUR TASK — for EACH link below");
L.push("-------------------------------");
L.push("1. Fetch the product page (a plain HTTP GET is enough for most; respect robots.txt and");
L.push("   rate-limit to ~1 request/sec per host). The L.L.Bean /llb/shop/<id> URLs redirect to the");
L.push("   real PDP — follow the redirect.");
L.push("2. Extract:");
L.push("   - product_title      : the real product name shown on the page (the single most important field)");
L.push("   - brand              : brand / designer if shown");
L.push('   - breadcrumb         : the site’s category breadcrumb path if any (e.g. "Women > Bottoms > Jeans")');
L.push('   - observed_item_type : the garment-type word(s) you see (e.g. "joggers", "overalls", "shirtdress")');
L.push("   (A few rows already have a title on file — shown as title=… below. For those just confirm and");
L.push("   categorize; no need to re-scrape the title.)");
L.push("3. Suggest a mother category. PREFER one of the EXISTING categories. Only invent a NEW category");
L.push('   if none genuinely fit, and keep it short + lowercase (e.g. "loungewear"). \'other\' is NOT a');
L.push("   valid answer — every row must get a real category or be flagged not_clothing=true. The whole");
L.push("   point of this task is to get these rows OUT of the 'other' bucket.");
L.push("");
L.push("EXISTING mother categories (prefer these):");
L.push("   " + APPAREL.join(", "));
L.push("   Mapping hints: overalls/shortalls/rompers/playsuits/catsuits/boilersuits/flight-suits -> jumpsuits ;");
L.push("   skirts/pants/shorts/jeans/joggers/leggings -> bottoms ; shirts/blouses/tanks/camis -> tops ;");
L.push("   coats/jackets -> outerwear ; swimsuits/bikinis -> swimwear.");
L.push("   NOTE: this site does NOT sell footwear. If a page is footwear (shoes/sandals/flip-flops) or");
L.push("   non-apparel (yoga mat, gift card, shipping/protection add-on), set not_clothing=true instead of");
L.push("   forcing a clothing category — those rows will be deleted, not categorized. Do NOT use 'other'.");
L.push("");
L.push("OUTPUT");
L.push("------");
L.push("Write one NDJSON object per line to: codex-uncategorized-product-pages.result.ndjson");
L.push("(save it next to this file — in the repo, not Downloads). Fields per line:");
L.push('   {"product_page_id":"","url":"","product_title":"","brand":"","breadcrumb":"",');
L.push('    "observed_item_type":"","suggested_mother_category":"","is_new_category":false,');
L.push('    "not_clothing":false,"confidence":"high|medium|low","evidence":"short reason"}');
L.push("Keep product_page_id EXACTLY as given so the result can be joined back to the DB.");
L.push("");
L.push(rule);
L.push(`LINKS (${rows.length}) — grouped by source`);
L.push(rule);

let i = 0;
let lastSource = null;
for (const r of rows) {
  if (r.source_site !== lastSource) {
    L.push("");
    L.push(`### ${r.source_site}`);
    lastSource = r.source_site;
  }
  i += 1;
  const sig = [];
  if (r.product_title) sig.push(`title=${r.product_title}`);
  if (r.brand) sig.push(`brand=${r.brand}`);
  const types = (r.observed_clothing_type_ids || []).filter((t) => t && t !== "other");
  if (types.length) sig.push(`observed_types=[${types.join(",")}]`);
  if (r.category_breadcrumb_path) sig.push(`breadcrumb=${r.category_breadcrumb_path}`);
  L.push(`[${i}] product_page_id=${r.product_page_id}${sig.length ? "  | " + sig.join("  | ") : ""}`);
  L.push(`    ${r.url}`);
}
L.push("");

writeFileSync(outPath, L.join("\n") + "\n");
console.log(`wrote ${path.relative(path.resolve(toolDir, "..", ".."), outPath)} (${rows.length} links)`);
