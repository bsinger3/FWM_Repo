#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
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
const unavailableStatuses = ["page_not_found", "product_unavailable", "redirected_to_non_product"];
const backfillVersion = "dev_image_product_link_status_backfill_20260618";
const migrationPath = path.join(repoRoot, "supabase/dev-migrations/20260618_dev_14_image_product_link_status.sql");

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

function parseJsonPsql(output, fallback = {}) {
  const trimmed = String(output || "").trim();
  return trimmed ? JSON.parse(trimmed) : fallback;
}

const unavailableStatusList = unavailableStatuses.map(sqlString).join(",");

const cleanupExtraColumnsSql = `
alter table public.images
  drop column if exists product_link_is_dead,
  drop column if exists product_link_status_checked_at,
  drop column if exists product_link_http_status,
  drop column if exists product_link_final_url,
  drop column if exists product_link_status_evidence,
  drop column if exists product_link_status_checker_version;

drop index if exists public.images_product_link_is_dead_idx;`;

const summarySql = `
with dead_pages as (
  select
    id,
    normalized_product_page_url,
    source_status
  from staging.product_pages
  where source_status in (${unavailableStatusList})
),
linked_images as (
  select
    i.id,
    i.product_page_id,
    i.product_link_status,
    i.original_url_display,
    i.product_page_url_display,
    dp.normalized_product_page_url,
    dp.source_status
  from public.images i
  join dead_pages dp on dp.id = i.product_page_id
),
stale_marked_images as (
  select i.id
  from public.images i
  left join dead_pages dp on dp.id = i.product_page_id
  where i.product_link_status is not null
    and dp.id is null
),
counts as (
  select source_status, count(*) as image_count
  from linked_images
  group by source_status
)
select jsonb_build_object(
  'dead_product_page_count', (select count(*) from dead_pages),
  'linked_image_count', (select count(*) from linked_images),
  'linked_images_by_status', coalesce((select jsonb_object_agg(source_status, image_count) from counts), '{}'::jsonb),
  'already_marked_count', (select count(*) from linked_images where product_link_status is not null),
  'stale_marked_count', (select count(*) from stale_marked_images),
  'needs_update_count', (
    select count(*)
    from linked_images
    where product_link_status is distinct from source_status
  ),
  'sample_images', coalesce((
    select jsonb_agg(to_jsonb(sample) order by sample.normalized_product_page_url, sample.image_id)
    from (
      select
        id::text as image_id,
        product_page_id::text as product_page_id,
        normalized_product_page_url,
        source_status,
        product_link_status,
        original_url_display,
        product_page_url_display
      from linked_images
      order by normalized_product_page_url, id
      limit 50
    ) sample
  ), '[]'::jsonb)
);`;

const applySql = `
with dead_pages as (
  select
    id,
    source_status
  from staging.product_pages
  where source_status in (${unavailableStatusList})
),
cleared as (
  update public.images i
  set
    product_link_status = null,
    updated_at = now()::text
  where i.product_link_status is not null
    and not exists (
      select 1
      from dead_pages dp
      where dp.id = i.product_page_id
    )
  returning i.id::text as image_id
),
updated as (
  update public.images i
  set
    product_link_status = dp.source_status,
    updated_at = now()::text
  from dead_pages dp
  where i.product_page_id = dp.id
  returning
    i.id::text as image_id,
    i.product_page_id::text as product_page_id,
    i.product_link_status
)
select jsonb_build_object(
  'cleared_count', (select count(*) from cleared),
  'updated_count', (select count(*) from updated),
  'updated', coalesce((select jsonb_agg(to_jsonb(updated) order by image_id) from updated), '[]'::jsonb)
);`;

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Image product-link status backfill guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });

  if (apply) {
    requireExplicitWriteFlag();
    const schemaSql = await readFile(migrationPath, "utf8");
    runPsql(process.env.DEV_DATABASE_URL, schemaSql);
    runPsql(process.env.DEV_DATABASE_URL, cleanupExtraColumnsSql);
  }

  const before = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, summarySql));
  const applyResult = apply ? parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, applySql)) : { cleared_count: 0, updated_count: 0, updated: [] };
  const after = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, summarySql));

  const reportPath = path.join(reportsDir, `dev_image_product_link_status_backfill_${timestampStem(new Date(generatedAt))}.json`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    backfill_version: backfillVersion,
    unavailable_statuses: unavailableStatuses,
    migration_path: migrationPath,
    before,
    apply_result: applyResult,
    after,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote image product-link status backfill report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Linked images: ${before.linked_image_count || 0}`);
  console.log(`Needs update: ${before.needs_update_count || 0}`);
  if (apply) {
    console.log(`Updated images: ${applyResult.updated_count || 0}`);
    console.log(`Cleared stale images: ${applyResult.cleared_count || 0}`);
  } else {
    console.log("Dry-run only. No Supabase rows were written.");
  }
  console.log(`After by status: ${JSON.stringify(after.linked_images_by_status || {})}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
