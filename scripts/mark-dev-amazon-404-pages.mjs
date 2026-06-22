#!/usr/bin/env node
/**
 * Mark Amazon product pages that returned HTTP 404 during the free taxonomy
 * backfill as DEAD, so their images stop showing up in front-end search.
 *
 * Why this is two writes, not one:
 *   The `match_by_measurements` search RPC (dev: 20260616_dev_03,
 *   prod: 20260520070000_hide_manual_dead_link_reports_from_search) decides which
 *   images are "dead" SOLELY by checking for a row in `public.image_reports` with
 *   reason='dead_link' AND a specific anon_id. It does NOT look at
 *   `staging.product_pages.source_status` or `public.images.product_link_status`.
 *   So to actually hide a 404 page's images we must:
 *     (1) record the truth on the page  -> source_status='page_not_found' (canonical,
 *         also feeds scripts/backfill-dev-image-product-link-status.mjs), AND
 *     (2) insert the dead_link image_reports rows the search filter honors.
 *
 * Source of 404s: the backfill progress sidecar / report rows where
 *   skip_reason === 'http_status_404'  (carry product_page_id + asin + http_status).
 *
 * DRY-RUN by default: reads the dev DB read-only, prints counts, writes a JSON
 * report, and prints the SQL it WOULD run. Pass --apply (with the dev guard) to
 * execute inside a single transaction.
 *
 * Usage:
 *   node scripts/mark-dev-amazon-404-pages.mjs                 # dry-run, newest sidecar
 *   node scripts/mark-dev-amazon-404-pages.mjs --source=/abs/report_or_sidecar.ndjson
 *   node scripts/mark-dev-amazon-404-pages.mjs --apply --i-understand-dev-writes
 *
 * NOTE on anon_id: defaults to 'manual_product_category_review_2026_05_20' — the ONLY
 * anon_id the current search filter honors, so the hide works with zero migration.
 * Override with --anon-id=... ONLY if you also extend the search filter to match it.
 */

import { execFileSync } from "node:child_process";
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { loadDotEnv } from "./lib/local-env.mjs";
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

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
await loadDotEnv({ cwd: repoRoot });

const apply = process.argv.includes("--apply");
const CHECKER_VERSION = "amazon_free_http_404_backfill_v1";

function parseArg(name, fallback = "") {
  const prefix = `--${name}=`;
  const hit = process.argv.find((a) => a.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}
const sourceArg = parseArg("source");
// The search RPC only honors this anon_id; keep it as the default so the hide works.
const anonId = parseArg("anon-id", "manual_product_category_review_2026_05_20");

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function runPsqlRead(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  return execFileSync(
    postgresClientTool("psql"),
    [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
    { encoding: "utf8", env: { ...process.env, ...connection.env }, maxBuffer: 1024 * 1024 * 128 },
  );
}

function runPsqlWrite(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...connection.env }, maxBuffer: 1024 * 1024 * 50 },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

async function latestSidecar(reportsDir) {
  // Prefer an explicit --source; else the backfill progress sidecar; else any
  // amazon_free audit report. All are NDJSON-or-JSON with rows carrying skip_reason.
  if (sourceArg) return path.resolve(sourceArg);
  const files = (await readdir(reportsDir))
    .filter((f) => /^amazon_taxonomy_worklist_\d{8}T\d{6}\d{3}Z_progress\.ndjson$/.test(f))
    .sort();
  if (files.length) return path.join(reportsDir, files[files.length - 1]);
  throw new Error(`No backfill progress sidecar found in ${reportsDir}; pass --source=PATH`);
}

// Collect distinct {product_page_id, asin} for rows that 404'd. Handles both the
// NDJSON sidecar (one row per line) and a JSON report ({ results: [...] }).
function extract404s(text) {
  const out = new Map();
  const add = (r) => {
    if (r && r.skip_reason === "http_status_404" && r.product_page_id) {
      out.set(r.product_page_id, { product_page_id: r.product_page_id, asin: r.asin || null });
    }
  };
  const trimmed = text.trim();
  if (trimmed.startsWith("{")) {
    try {
      for (const r of JSON.parse(trimmed).results || []) add(r);
      return [...out.values()];
    } catch {
      /* fall through to NDJSON */
    }
  }
  for (const line of trimmed.split("\n")) {
    if (!line.trim()) continue;
    try {
      add(JSON.parse(line));
    } catch {
      /* skip */
    }
  }
  return [...out.values()];
}

function pageUpdateSql(ids) {
  const idList = ids.map((id) => `${sqlString(id)}::uuid`).join(", ");
  return `
update staging.product_pages
set
  source_status = 'page_not_found',
  source_http_status = 404,
  source_status_checked_at = now(),
  source_status_evidence = 'Amazon /dp/{ASIN} returned HTTP 404 during free taxonomy backfill',
  source_status_checker_version = ${sqlString(CHECKER_VERSION)}
where id in (${idList});`;
}

// Insert the dead_link reports the search filter honors, for every image on a 404
// page, skipping any that already have one (no unique constraint on image_reports).
function imageReportInsertSql(ids) {
  const idList = ids.map((id) => `${sqlString(id)}::uuid`).join(", ");
  return `
insert into public.image_reports (image_id, reason, anon_id)
select i.id, 'dead_link'::public.image_report_reason, ${sqlString(anonId)}
from public.images i
where i.product_page_id in (${idList})
  and not exists (
    select 1 from public.image_reports ir
    where ir.image_id = i.id
      and ir.reason = 'dead_link'::public.image_report_reason
      and ir.anon_id = ${sqlString(anonId)}
  );`;
}

async function main() {
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  const sourcePath = await latestSidecar(reportsDir);
  if (!existsSync(sourcePath)) throw new Error(`Source not found: ${sourcePath}`);

  const rows404 = extract404s(await readFile(sourcePath, "utf8"));
  if (!rows404.length) {
    console.log(`No http_status_404 rows in ${sourcePath}. Nothing to mark.`);
    return;
  }
  const ids = rows404.map((r) => r.product_page_id);

  const databaseUrl = process.env.DEV_DATABASE_URL;
  if (!databaseUrl) throw new Error("DEV_DATABASE_URL is not set (env or .env).");
  if (process.env.PROD_DATABASE_URL && databaseUrl === process.env.PROD_DATABASE_URL) {
    throw new Error("Refusing to run: DEV_DATABASE_URL equals PROD_DATABASE_URL.");
  }

  // Read-only: how many of these pages exist, and how many images would be hidden.
  const idList = ids.map((id) => `${sqlString(id)}::uuid`).join(", ");
  const probe = runPsqlRead(
    databaseUrl,
    `select
       (select count(*) from staging.product_pages where id in (${idList})) as pages_found,
       (select count(*) from staging.product_pages where id in (${idList}) and source_status = 'page_not_found') as pages_already_dead,
       (select count(*) from public.images where product_page_id in (${idList})) as images_linked,
       (select count(*) from public.images i where i.product_page_id in (${idList})
          and not exists (select 1 from public.image_reports ir
            where ir.image_id = i.id and ir.reason = 'dead_link'::public.image_report_reason and ir.anon_id = ${sqlString(anonId)})
       ) as images_to_hide;`,
  )
    .trim()
    .split("|")
    .map((n) => Number(n));
  const [pagesFound, pagesAlreadyDead, imagesLinked, imagesToHide] = probe;

  const pageSql = pageUpdateSql(ids);
  const reportSql = imageReportInsertSql(ids);
  const txn = `begin;\n${pageSql}\n${reportSql}\ncommit;`;

  console.log(`Source:                 ${sourcePath}`);
  console.log(`DB:                     ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`404 product pages:      ${ids.length}`);
  console.log(`  found in DB:          ${pagesFound}`);
  console.log(`  already page_not_found:${pagesAlreadyDead}`);
  console.log(`Images linked to them:  ${imagesLinked}`);
  console.log(`Images that would hide: ${imagesToHide}  (dead_link reports, anon_id=${anonId})`);

  const outReport = {
    generated_at_note: "stamp added by caller; Date.now intentionally avoided in libs",
    mode: apply ? "apply" : "dry-run",
    source_path: sourcePath,
    anon_id: anonId,
    checker_version: CHECKER_VERSION,
    page_count: ids.length,
    pages_found: pagesFound,
    pages_already_dead: pagesAlreadyDead,
    images_linked: imagesLinked,
    images_to_hide: imagesToHide,
    product_page_ids: ids,
    sql: txn,
  };
  await mkdir(reportsDir, { recursive: true });
  const outPath = path.join(reportsDir, `dev_amazon_404_mark_${apply ? "applied" : "dryrun"}.json`);
  await writeFile(outPath, JSON.stringify(outReport, null, 2) + "\n", "utf8");
  console.log(`Wrote plan -> ${outPath}`);

  if (!apply) {
    console.log("\nDry-run only. No rows written. Re-run with --apply --i-understand-dev-writes to execute.");
    console.log("\n--- SQL that WOULD run ---\n" + txn);
    return;
  }

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Amazon 404 mark guard" });
  assertApprovedDevDatabaseUrl(databaseUrl);
  requireExplicitWriteFlag();
  runPsqlWrite(databaseUrl, txn);
  console.log(`Applied: marked ${pagesFound} pages page_not_found, hid ~${imagesToHide} images from search.`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
