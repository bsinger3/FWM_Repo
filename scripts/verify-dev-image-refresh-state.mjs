#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

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
  const trimmed = output.trim();
  return trimmed ? JSON.parse(trimmed) : fallback;
}

function ok(name, condition, details = null) {
  return { name, ok: Boolean(condition), details };
}

function stateSql() {
  return `
with image_counts as (
  select
    count(*)::integer as total_images,
    count(*) filter (where original_url_display is null or btrim(original_url_display) = '')::integer as missing_image_url,
    count(*) filter (where coalesce(product_page_url_display, monetized_product_url_display) is null)::integer as missing_product_url,
    count(*) filter (where product_page_id is not null)::integer as images_with_product_page_id,
    count(*) filter (where review_id is not null)::integer as images_with_review_id,
    count(*) filter (where crop_spec is not null)::integer as images_with_crop_spec,
    count(*) filter (where crop_spec is not null and coalesce(crop_spec->>'rotationDeg', crop_spec->>'rotation_deg') is not null and coalesce(crop_spec->>'rotationDeg', crop_spec->>'rotation_deg') not in ('0', '90', '180', '270'))::integer as invalid_crop_rotations,
    count(*) filter (where weeks_pregnant is not null and pregnancy_evidence is null)::integer as weeks_without_evidence,
    count(*) filter (where prettiness_score is not null)::integer as prettiness_populated,
    count(*) filter (where image_orientation_degrees is not null and crop_spec->>'rotationDeg' is distinct from image_orientation_degrees::text)::integer as orientation_crop_mismatch
  from public.images
),
review_counts as (
  select
    count(*)::integer as total_reviews,
    count(*) filter (where review_identity_key like 'baseline:%')::integer as baseline_reviews,
    count(*) filter (where product_page_id is null)::integer as reviews_missing_product_page_id
  from public.reviews
),
product_counts as (
  select
    count(*)::integer as total_product_pages,
    count(*) filter (where source_status_checked_at is not null)::integer as status_checked_pages,
    count(*) filter (where category_checked_at is not null)::integer as taxonomy_checked_pages
  from staging.product_pages
),
tag_counts as (
  select
    (select count(*)::integer from staging.product_page_clothing_type_tags) as clothing_type_tags,
    (select count(*)::integer from staging.product_page_attribute_tags) as attribute_tags
),
trigger_counts as (
  select
    count(*) filter (where event_object_schema = 'public' and event_object_table = 'reviews' and trigger_name = 'set_reviews_updated_at')::integer as reviews_updated_at_triggers,
    count(*) filter (where event_object_schema = 'public' and event_object_table = 'images' and trigger_name = 'set_images_updated_at')::integer as images_updated_at_triggers
  from information_schema.triggers
)
select jsonb_build_object(
  'images', to_jsonb(image_counts),
  'reviews', to_jsonb(review_counts),
  'product_pages', to_jsonb(product_counts),
  'tags', to_jsonb(tag_counts),
  'triggers', to_jsonb(trigger_counts)
)
from image_counts, review_counts, product_counts, tag_counts, trigger_counts;`;
}

function buildChecks(state) {
  return [
    ok("images_exist", Number(state.images?.total_images || 0) > 0, state.images?.total_images),
    ok("all_images_have_image_url", Number(state.images?.missing_image_url || 0) === 0, state.images),
    ok("all_images_have_product_or_monetized_url", Number(state.images?.missing_product_url || 0) === 0, state.images),
    ok("some_images_have_product_page_id", Number(state.images?.images_with_product_page_id || 0) > 0, state.images),
    ok("some_images_have_review_id", Number(state.images?.images_with_review_id || 0) > 0, state.images),
    ok("crop_rotations_are_allowed", Number(state.images?.invalid_crop_rotations || 0) === 0, state.images),
    ok("weeks_pregnant_has_evidence", Number(state.images?.weeks_without_evidence || 0) === 0, state.images),
    ok("prettiness_is_still_schema_only", Number(state.images?.prettiness_populated || 0) === 0, state.images),
    ok("orientation_fields_match_crop_spec", Number(state.images?.orientation_crop_mismatch || 0) === 0, state.images),
    ok("reviews_exist", Number(state.reviews?.total_reviews || 0) > 0, state.reviews),
    ok("reviews_have_product_page_id", Number(state.reviews?.reviews_missing_product_page_id || 0) === 0, state.reviews),
    ok("product_pages_exist", Number(state.product_pages?.total_product_pages || 0) > 0, state.product_pages),
    ok("status_has_some_checked_pages", Number(state.product_pages?.status_checked_pages || 0) > 0, state.product_pages),
    ok("taxonomy_has_some_checked_pages", Number(state.product_pages?.taxonomy_checked_pages || 0) > 0, state.product_pages),
    ok("taxonomy_tags_exist", Number(state.tags?.clothing_type_tags || 0) > 0 && Number(state.tags?.attribute_tags || 0) > 0, state.tags),
    ok("reviews_updated_at_trigger_exists", Number(state.triggers?.reviews_updated_at_triggers || 0) === 1, state.triggers),
    ok("images_updated_at_trigger_exists", Number(state.triggers?.images_updated_at_triggers || 0) === 1, state.triggers),
  ];
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Dev image refresh state verifier guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const state = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, stateSql()));
  const checks = buildChecks(state);
  const passed = checks.every((check) => check.ok);

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(
    reportsDir,
    `dev_image_refresh_state_verify_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`,
  );
  await writeFile(
    reportPath,
    JSON.stringify(
      {
        generated_at: generatedAt,
        supabase_url: guard.supabaseUrl,
        supabase_project_ref: guard.projectRef,
        passed,
        checks,
        state,
      },
      null,
      2,
    ) + "\n",
    "utf8",
  );

  console.log(`Wrote dev image refresh state verification: ${reportPath}`);
  console.log(`Checks passed: ${checks.filter((check) => check.ok).length}/${checks.length}`);
  console.log(`Passed: ${passed}`);
  if (!passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
