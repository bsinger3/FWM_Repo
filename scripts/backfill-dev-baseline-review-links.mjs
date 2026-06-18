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
const sampleLimit = Math.max(1, Number(process.argv.find((arg) => arg.startsWith("--sample-limit="))?.split("=")[1] || 25));
const BASELINE_SOURCE_FILE = "production_baseline_pg_dump";

function runPsql(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      {
        encoding: "utf8",
        env: { ...process.env, ...connection.env },
        maxBuffer: 1024 * 1024 * 20,
      },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

function parsePipeRows(output) {
  return output
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => line.split("|"));
}

function dryRunSql() {
  return `
with candidates as (
  select
    id,
    staging.normalize_product_url(product_page_url_display) as normalized_product_page_url,
    original_url_display,
    source_site_display,
    brand,
    clothing_type_id
  from public.images
  where review_id is null
    and product_page_id is null
    and review_row_key is null
),
valid_candidates as (
  select *
  from candidates
  where nullif(normalized_product_page_url, '') is not null
),
missing_url_candidates as (
  select *
  from candidates
  where nullif(normalized_product_page_url, '') is null
)
select
  (select count(*) from candidates) as total_candidates,
  (select count(*) from valid_candidates) as valid_candidates,
  (select count(distinct normalized_product_page_url) from valid_candidates) as distinct_product_pages,
  (select count(*) from missing_url_candidates) as missing_product_url_candidates,
  coalesce((
    select jsonb_agg(
      jsonb_build_object(
        'id', id,
        'normalized_product_page_url', normalized_product_page_url,
        'original_url_display', original_url_display,
        'review_row_key', 'baseline:' || normalized_product_page_url || ':' || id
      )
      order by id
    )
    from (
      select *
      from valid_candidates
      order by id
      limit ${sampleLimit}
    ) sample
  ), '[]'::jsonb) as sample_backfills,
  coalesce((
    select jsonb_agg(
      jsonb_build_object(
        'id', id,
        'original_url_display', original_url_display
      )
      order by id
    )
    from (
      select *
      from missing_url_candidates
      order by id
      limit ${sampleLimit}
    ) sample
  ), '[]'::jsonb) as missing_product_url_samples
;`;
}

function applySql() {
  return `
begin;

with candidates as (
  select
    image.id,
    staging.normalize_product_url(image.product_page_url_display) as normalized_product_page_url,
    image.source_site_display,
    image.brand,
    image.clothing_type_id
  from public.images image
  where image.review_id is null
    and image.product_page_id is null
    and image.review_row_key is null
    and nullif(staging.normalize_product_url(image.product_page_url_display), '') is not null
),
product_page_inputs as (
  select
    normalized_product_page_url,
    max(nullif(source_site_display, '')) as source_site,
    max(nullif(brand, '')) as brand,
    coalesce(array_agg(distinct clothing_type_id) filter (where clothing_type_id is not null), '{}'::text[]) as observed_clothing_type_ids
  from candidates
  group by normalized_product_page_url
)
insert into staging.product_pages (
  normalized_product_page_url,
  source_site,
  brand,
  observed_clothing_type_ids,
  image_row_count,
  first_seen_at,
  last_seen_at,
  populated_from,
  raw_metadata,
  updated_at
)
select
  normalized_product_page_url,
  source_site,
  brand,
  observed_clothing_type_ids,
  0,
  now(),
  now(),
  'baseline_review_link_backfill',
  jsonb_build_object('review_identity_strategy', 'baseline_one_image_fallback'),
  now()
from product_page_inputs
on conflict (normalized_product_page_url) do update
set
  source_site = coalesce(excluded.source_site, staging.product_pages.source_site),
  brand = coalesce(excluded.brand, staging.product_pages.brand),
  observed_clothing_type_ids = coalesce((
    select array_agg(distinct value order by value)
    from unnest(staging.product_pages.observed_clothing_type_ids || excluded.observed_clothing_type_ids) as value
    where value is not null
  ), '{}'::text[]),
  raw_metadata = staging.product_pages.raw_metadata || excluded.raw_metadata,
  updated_at = now();

with candidates as (
  select
    image.id,
    staging.normalize_product_url(image.product_page_url_display) as normalized_product_page_url,
    image.source_site_display,
    image.reviewer_name_raw,
    image.review_date,
    image.date_review_submitted_raw,
    image.user_comment
  from public.images image
  where image.review_id is null
    and image.product_page_id is null
    and image.review_row_key is null
    and nullif(staging.normalize_product_url(image.product_page_url_display), '') is not null
)
insert into public.reviews (
  product_page_id,
  normalized_product_page_url,
  source_site,
  review_identity_key,
  reviewer_name_raw,
  review_date_raw,
  user_comment,
  source_file,
  created_at,
  updated_at
)
select
  page.id,
  candidates.normalized_product_page_url,
  nullif(candidates.source_site_display, ''),
  'baseline:' || candidates.normalized_product_page_url || ':' || candidates.id,
  nullif(candidates.reviewer_name_raw, ''),
  nullif(coalesce(candidates.date_review_submitted_raw, candidates.review_date), ''),
  nullif(candidates.user_comment, ''),
  '${BASELINE_SOURCE_FILE}',
  now(),
  now()
from candidates
join staging.product_pages page
  on page.normalized_product_page_url = candidates.normalized_product_page_url
on conflict (review_identity_key) do update
set
  product_page_id = excluded.product_page_id,
  normalized_product_page_url = excluded.normalized_product_page_url,
  source_site = coalesce(excluded.source_site, public.reviews.source_site),
  reviewer_name_raw = coalesce(excluded.reviewer_name_raw, public.reviews.reviewer_name_raw),
  review_date_raw = coalesce(excluded.review_date_raw, public.reviews.review_date_raw),
  user_comment = coalesce(excluded.user_comment, public.reviews.user_comment),
  source_file = excluded.source_file,
  updated_at = now();

with candidates as (
  select
    image.id,
    staging.normalize_product_url(image.product_page_url_display) as normalized_product_page_url
  from public.images image
  where image.review_id is null
    and image.product_page_id is null
    and image.review_row_key is null
    and nullif(staging.normalize_product_url(image.product_page_url_display), '') is not null
)
update public.images image
set
  product_page_id = page.id,
  review_id = review.id,
  review_row_key = 'baseline:' || candidates.normalized_product_page_url || ':' || candidates.id,
  source_file = '${BASELINE_SOURCE_FILE}',
  updated_at = now()
from candidates
join staging.product_pages page
  on page.normalized_product_page_url = candidates.normalized_product_page_url
join public.reviews review
  on review.review_identity_key = 'baseline:' || candidates.normalized_product_page_url || ':' || candidates.id
where image.id = candidates.id;

update staging.product_pages page
set
  image_row_count = coalesce(counts.image_count, 0),
  last_seen_at = now(),
  updated_at = now()
from (
  select
    product_page_id,
    count(*)::integer as image_count
  from public.images
  where product_page_id is not null
  group by product_page_id
) counts
where page.id = counts.product_page_id;

commit;

select
  (select count(*) from public.images where review_id is null) as images_missing_review_id,
  (select count(*) from public.images where product_page_id is null) as images_missing_product_page_id,
  (select count(*) from public.images where review_row_key is null) as images_missing_review_row_key,
  (select count(*) from public.reviews where source_file = '${BASELINE_SOURCE_FILE}') as baseline_reviews;
`;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Baseline review-link backfill guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_baseline_review_link_backfill_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`);

  const dryRows = parsePipeRows(runPsql(process.env.DEV_DATABASE_URL, dryRunSql()));
  const [
    totalCandidates,
    validCandidates,
    distinctProductPages,
    missingProductUrlCandidates,
    sampleBackfills,
    missingProductUrlSamples,
  ] = dryRows[0];

  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    review_identity_strategy: "baseline:<normalized_product_url>:<image_id>",
    source_file: BASELINE_SOURCE_FILE,
    total_candidates: Number(totalCandidates),
    valid_candidates: Number(validCandidates),
    distinct_product_pages: Number(distinctProductPages),
    missing_product_url_candidates: Number(missingProductUrlCandidates),
    sample_backfills: JSON.parse(sampleBackfills || "[]"),
    missing_product_url_samples: JSON.parse(missingProductUrlSamples || "[]"),
    apply_result: null,
  };

  console.log(`Wrote baseline review-link backfill report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Resolved Supabase: ${report.supabase_url} (${report.supabase_project_ref})`);
  console.log(`Total baseline-link candidates: ${report.total_candidates}`);
  console.log(`Valid candidates: ${report.valid_candidates}`);
  console.log(`Distinct product pages: ${report.distinct_product_pages}`);
  console.log(`Missing product URL candidates: ${report.missing_product_url_candidates}`);

  if (apply) {
    requireExplicitWriteFlag();
    const resultRows = parsePipeRows(runPsql(process.env.DEV_DATABASE_URL, applySql()));
    const result = resultRows.at(-1) || [];
    report.apply_result = {
      images_missing_review_id: Number(result[0]),
      images_missing_product_page_id: Number(result[1]),
      images_missing_review_row_key: Number(result[2]),
      baseline_reviews: Number(result[3]),
    };
    console.log(`Apply result: ${JSON.stringify(report.apply_result)}`);
  } else {
    console.log("Dry-run only. No Supabase rows were written.");
  }

  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
