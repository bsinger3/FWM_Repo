#!/usr/bin/env node
// Generates the Codex brief for scraping product titles for staging.product_pages
// rows that are missing product_title_raw (any category). Dev-guarded, read-only.
// Writes two files next to itself:
//   codex-missing-titles-input.ndjson  — one JSON row per page (machine-readable)
//   codex-missing-titles-prompt.txt    — the instructions for Codex
//
//   node tools/missing-title-scrape/build-codex-missing-titles.mjs

import { execFileSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  printGuardSummary,
} from "../../scripts/lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "../../scripts/lib/postgres-client.mjs";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(toolDir, "..", "..");
const inputPath = path.join(toolDir, "codex-missing-titles-input.ndjson");
const promptPath = path.join(toolDir, "codex-missing-titles-prompt.txt");

function runPsql(databaseUrl, sql) {
  const c = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...c.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...c.env }, maxBuffer: 1024 * 1024 * 200 },
    );
  } catch (e) {
    throw new Error(String(e.stderr || e.message || "").replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

const guard = await assertApprovedDevSupabase();
printGuardSummary(guard, { prefix: "codex-missing-titles:build" });
const databaseUrl = process.env.DEV_DATABASE_URL;
assertApprovedDevDatabaseUrl(databaseUrl);

// Untitled pages, excluding ones already known dead / robots-disallowed / redirected.
const FILTER =
  "coalesce(trim(product_title_raw),'')='' and " +
  "coalesce(source_status,'') not in ('page_not_found','robots_disallowed','redirected_to_non_product')";

const rows = JSON.parse(
  runPsql(
    databaseUrl,
    `select coalesce(jsonb_agg(row_to_json(t)),'[]'::jsonb) from (
       select id::text as product_page_id, normalized_product_page_url as url, source_site,
              brand, mother_category_id, coalesce(source_status,'unknown') as source_status
       from staging.product_pages where ${FILTER}
       order by source_site, normalized_product_page_url
     ) t;`,
  ).trim() || "[]",
);

mkdirSync(toolDir, { recursive: true });
// Machine-readable input: one compact JSON object per line.
writeFileSync(inputPath, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");

const bySource = {};
for (const r of rows) bySource[r.source_site] = (bySource[r.source_site] || 0) + 1;
const sourceLines = Object.entries(bySource)
  .sort((a, b) => b[1] - a[1])
  .map(([s, n]) => `   ${String(n).padStart(5)}  ${s}`);

const L = [];
const rule = "=".repeat(92);
L.push("FWM — Codex task: scrape missing product TITLES for dev product pages (save locally, NO DB writes)");
L.push("Generated 2026-06-25 · dev DB ref gosqgqpftqlawvnyelkt · staging.product_pages");
L.push(rule);
L.push("");
L.push("CONTEXT");
L.push("-------");
L.push(`There are ${rows.length} rows in the Friends With Measurements dev database (staging.product_pages)`);
L.push("that have NO product_title_raw on file. They are already categorized — the only thing missing is the");
L.push("human-readable product title, which is needed for the product cards. Your job is to scrape the real");
L.push("title for each. (Pages already known dead / robots-disallowed have been excluded from this list.)");
L.push("");
L.push("INPUT");
L.push("-----");
L.push("Read the companion file:  codex-missing-titles-input.ndjson  (one JSON object per line)");
L.push("   {\"product_page_id\":\"…\",\"url\":\"…\",\"source_site\":\"…\",\"brand\":null,\"mother_category_id\":\"…\",\"source_status\":\"unknown\"}");
L.push(`Counts by source (${rows.length} total):`);
L.push(...sourceLines);
L.push("");
L.push("YOUR TASK — for EACH row");
L.push("------------------------");
L.push("1. Fetch the `url`. Be polite: respect robots.txt, rate-limit to ~1 request/sec PER HOST, set a");
L.push("   normal User-Agent, and make the run resumable/cached so a re-run doesn't refetch what you have.");
L.push("   Per-source notes:");
L.push("   - amazon.com (~4.6k, the bulk): a plain GET of the canonical /dp/<ASIN> page returns the title");
L.push("     in <title>/og:title/#productTitle — no headless browser needed (see the repo's");
L.push("     'amazon taxonomy free fetch' approach). Back off on CAPTCHA/503 and retry later.");
L.push("   - renttherunway.com (~3.1k): title is in og:title / JSON-LD Product.name.");
L.push("   - bloomchic.com: previously rate-limited (HTTP 429) — slow down, retry; it is NOT dead.");
L.push("   - others (nuuly, shopcider, thecommense, chicwish, berlook, shapermint, rihoas, ever-pretty):");
L.push("     og:title or JSON-LD Product.name.");
L.push("2. Extract:");
L.push("   - product_title : the real product name shown on the page (REQUIRED — the whole point).");
L.push("   - brand         : brand/designer if easily available (optional bonus; many rows lack it).");
L.push("   - breadcrumb    : the site's category breadcrumb path if present (optional bonus).");
L.push("   Do NOT guess or synthesize a title. If you cannot get a real one, record the failure (below).");
L.push("");
L.push("OUTPUT — SAVE LOCALLY ONLY. DO NOT WRITE TO ANY DATABASE.");
L.push("--------------------------------------------------------");
L.push("Write one NDJSON object per line to:  codex-missing-titles.result.ndjson");
L.push("(save it next to this file, in the repo — NOT Downloads, NOT the database). Fields per line:");
L.push("   {\"product_page_id\":\"\",\"url\":\"\",\"product_title\":\"\",\"brand\":\"\",\"breadcrumb\":\"\",");
L.push("    \"scraped_ok\":true,\"http_status\":200,\"note\":\"\"}");
L.push("- Keep product_page_id EXACTLY as given so the result can be joined back to the DB later.");
L.push("- On failure set scraped_ok=false, leave product_title empty, and put the reason in note");
L.push("  (e.g. \"404\", \"captcha\", \"429 after retries\"). A human will load the results into the DB in a");
L.push("  separate, reviewed step — your run must make ZERO database writes.");
L.push("");
L.push("It is fine to write the result incrementally (append as you go) so progress survives interruptions.");
L.push("");
writeFileSync(promptPath, L.join("\n") + "\n");

console.log(`wrote ${path.relative(repoRoot, inputPath)} (${rows.length} rows)`);
console.log(`wrote ${path.relative(repoRoot, promptPath)}`);
