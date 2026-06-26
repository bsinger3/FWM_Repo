#!/usr/bin/env node
// Load Codex's scraped product titles (codex-missing-titles.result.ndjson) into
// staging.product_pages.product_title_raw. Only rows scraped_ok=true with a
// non-empty title are loaded, and only where the page is STILL untitled (never
// clobber an existing title). Failures (mostly Amazon CAPTCHA) are skipped.
//
// Dry-run by default. --apply requires FWM_DEV_DB_WRITE_OK. A before-snapshot of
// every touched row is written to FWM_Data/_reports for reversibility.
//
//   node tools/missing-title-scrape/load-missing-titles.mjs            # dry run
//   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
//     node tools/missing-title-scrape/load-missing-titles.mjs --apply

import { execFileSync } from "node:child_process";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../image-review-dashboard/paths.mjs";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "../../scripts/lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "../../scripts/lib/postgres-client.mjs";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(toolDir, "..", "..");
const resultPath = path.join(toolDir, "codex-missing-titles.result.ndjson");
const apply = process.argv.includes("--apply");
const TITLE_SOURCE = "codex_missing_title_scrape_v1";

function runPsql(databaseUrl, sql) {
  const c = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...c.env }, maxBuffer: 1024 * 1024 * 200 },
    );
  } catch (e) {
    throw new Error(String(e.stderr || e.message || "").replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

const sqlStr = (v) => (v == null ? "null" : `'${String(v).replaceAll("'", "''")}'`);

async function main() {
  const guard = await assertApprovedDevSupabase({ requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "load-missing-titles" });
  const databaseUrl = process.env.DEV_DATABASE_URL;
  assertApprovedDevDatabaseUrl(databaseUrl);

  const lines = (await readFile(resultPath, "utf8")).split("\n").filter((l) => l.trim());
  const good = [];
  const seen = new Set();
  for (const l of lines) {
    let o;
    try { o = JSON.parse(l); } catch { continue; }
    const title = (o.product_title || "").trim();
    if (o.scraped_ok === false || !title || !o.product_page_id) continue;
    if (seen.has(o.product_page_id)) continue;
    seen.add(o.product_page_id);
    good.push({ id: o.product_page_id, title });
  }
  console.log(`Scraped rows: ${lines.length} | usable (ok + title): ${good.length}`);

  // Which of these are still in the DB AND still untitled (don't clobber).
  const idList = good.map((g) => `${sqlStr(g.id)}::uuid`).join(",");
  const eligibleIds = new Set(
    runPsql(
      databaseUrl,
      `select id::text from staging.product_pages
         where id in (${idList}) and coalesce(trim(product_title_raw),'')='';`,
    ).trim().split("\n").map((s) => s.trim()).filter(Boolean),
  );
  const toWrite = good.filter((g) => eligibleIds.has(g.id));
  const alreadyTitled = good.length - toWrite.length;
  console.log(`Will set product_title_raw on: ${toWrite.length}`);
  console.log(`Skipped (already titled or row gone): ${alreadyTitled}`);

  if (!toWrite.length) { console.log("\nNothing to write."); return; }
  if (!apply) {
    console.log("\nSample of titles to load:");
    for (const g of toWrite.slice(0, 5)) console.log(`  ${g.id}  ${g.title.slice(0, 70)}`);
    console.log(`\nDRY RUN — no DB writes. Re-run with --apply (and FWM_DEV_DB_WRITE_OK).`);
    return;
  }
  requireExplicitWriteFlag();

  // Reversible snapshot (these are all currently-empty titles, but capture anyway).
  const writeIds = toWrite.map((g) => `${sqlStr(g.id)}::uuid`).join(",");
  const snap = runPsql(
    databaseUrl,
    `select coalesce(json_agg(t),'[]') from (
       select id::text, product_title_raw from staging.product_pages where id in (${writeIds})
     ) t;`,
  ).trim();
  const reportDir = path.join(fwmDataDir(), "_reports");
  await mkdir(reportDir, { recursive: true });
  const stem = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "");
  const snapPath = path.join(reportDir, `missing_titles_load_${stem}_before.json`);
  await writeFile(snapPath, snap + "\n");
  console.log(`\nReversible snapshot: ${snapPath}`);

  // Chunked UPDATE ... FROM (VALUES ...).
  const CHUNK = 500;
  let written = 0;
  for (let i = 0; i < toWrite.length; i += CHUNK) {
    const chunk = toWrite.slice(i, i + CHUNK);
    const values = chunk.map((g) => `(${sqlStr(g.id)}::uuid, ${sqlStr(g.title)})`).join(",");
    runPsql(
      databaseUrl,
      `update staging.product_pages p
         set product_title_raw = v.title,
             populated_from = coalesce(p.populated_from, '${TITLE_SOURCE}'),
             updated_at = now()
       from (values ${values}) as v(id, title)
       where p.id = v.id and coalesce(trim(p.product_title_raw),'')='';`,
    );
    written += chunk.length;
    if (written % 2000 < CHUNK) console.log(`  ...${Math.min(written, toWrite.length)}/${toWrite.length}`);
  }
  console.log(`\nAPPLIED: set product_title_raw on ${toWrite.length} product pages.`);
}

main().catch((e) => { console.error(e.message || e); process.exit(1); });
