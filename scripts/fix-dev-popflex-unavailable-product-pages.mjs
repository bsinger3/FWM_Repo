#!/usr/bin/env node

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

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const correctionVersion = "manual_popflex_homepage_redirect_correction_20260618";

const homepageRedirectUrls = [
  "https://popflexactive.com/products/go-with-the-flow-long-sleeve-jumpsuit-black-1st-edition",
  "https://popflexactive.com/products/go-with-the-flow-long-sleeve-jumpsuit-deep-cherry-1st-edition",
  "https://popflexactive.com/products/go-with-the-flow-long-sleeve-jumpsuit-deep-forest",
];

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function timestampStem(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(".", "");
}

function runPsql(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      {
        encoding: "utf8",
        env: { ...process.env, ...connection.env },
        maxBuffer: 1024 * 1024 * 50,
      },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

function parseJsonPsql(output) {
  const trimmed = String(output || "").trim();
  return trimmed ? JSON.parse(trimmed) : [];
}

const targetUrlsSql = homepageRedirectUrls.map(sqlString).join(",");

const readSql = `
select coalesce(jsonb_agg(row_to_json(row_data) order by row_data.normalized_product_page_url), '[]'::jsonb)
from (
  select
    id::text as product_page_id,
    normalized_product_page_url,
    product_title_raw,
    source_status,
    source_http_status,
    source_final_url,
    source_redirected,
    source_final_url_type,
    source_status_evidence,
    source_status_checker_version
  from staging.product_pages
  where normalized_product_page_url in (${targetUrlsSql})
) row_data;`;

const applySql = `
begin;

update staging.product_pages
set
  source_status = 'redirected_to_non_product',
  source_status_checked_at = now(),
  source_http_status = 200,
  source_final_url = 'https://www.popflexactive.com/',
  source_redirected = true,
  source_final_url_type = 'non_product',
  source_status_evidence = 'Manual live check: legacy POPFLEX product URL redirects to retailer homepage / non-product page.',
  source_status_error = null,
  source_status_checker_version = '${correctionVersion}',
  robots_disallowed = false,
  raw_metadata = coalesce(raw_metadata, '{}'::jsonb) || jsonb_build_object(
    'manual_unavailable_status_corrected_at', now(),
    'manual_unavailable_status_reason', 'legacy POPFLEX product URL redirects to homepage'
  ),
  updated_at = now()
where normalized_product_page_url in (${targetUrlsSql});

commit;`;

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "POPFLEX unavailable product-page correction guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const before = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, readSql));
  if (apply) {
    requireExplicitWriteFlag();
    runPsql(process.env.DEV_DATABASE_URL, applySql);
  }
  const after = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, readSql));

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_popflex_unavailable_product_page_correction_${timestampStem(new Date(generatedAt))}.json`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    correction_version: correctionVersion,
    target_url_count: homepageRedirectUrls.length,
    before,
    after,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote POPFLEX unavailable product-page correction report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Target URLs: ${homepageRedirectUrls.length}`);
  console.log(`Rows found: ${before.length}`);
  if (apply) console.log(`Corrected rows: ${after.filter((row) => row.source_status === "redirected_to_non_product").length}`);
  else console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
