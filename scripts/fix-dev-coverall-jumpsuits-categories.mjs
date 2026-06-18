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
const correctionVersion = "manual_coverall_jumpsuits_category_correction_20260618";

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
  const jsonLine = String(output || "")
    .trim()
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line.startsWith("{") || line.startsWith("["));
  return jsonLine ? JSON.parse(jsonLine) : fallback;
}

const targetPredicate = `
  pp.normalized_product_page_url ilike '%coverall%'
  or pp.product_title_raw ilike '%coverall%'
  or exists (
    select 1
    from staging.product_page_clothing_type_tags pct
    where pct.product_page_id = pp.id
      and pct.clothing_type_id = 'coverall'
  )
`;

const targetRowsSql = `
select coalesce(jsonb_agg(row_to_json(row_data) order by row_data.normalized_product_page_url), '[]'::jsonb)
from (
  select
    pp.id::text as product_page_id,
    pp.normalized_product_page_url,
    pp.product_title_raw,
    pp.mother_category_id,
    pp.category_confidence,
    pp.category_source_field,
    pp.category_extractor_version
  from staging.product_pages pp
  where ${targetPredicate}
) row_data;`;

const applySql = `
begin;

insert into staging.clothing_mother_categories
  (id, label, display_label, sort_order, frontend_sort_order, is_frontend_filter)
values
  ('jumpsuits', 'Jumpsuits', 'Jumpsuits', 35, 35, true)
on conflict (id) do update set
  label = excluded.label,
  display_label = excluded.display_label,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  is_frontend_filter = excluded.is_frontend_filter,
  updated_at = now();

insert into staging.clothing_type_tags
  (id, mother_category_id, label, display_label, aliases, sort_order, frontend_sort_order, is_search_tag, is_frontend_filter, search_boost)
values
  ('coverall', 'jumpsuits', 'Coverall', 'Coverall', array['coveralls'], 10, 10, true, true, 1.4)
on conflict (id) do update set
  mother_category_id = excluded.mother_category_id,
  label = excluded.label,
  display_label = excluded.display_label,
  aliases = excluded.aliases,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  is_search_tag = excluded.is_search_tag,
  is_frontend_filter = excluded.is_frontend_filter,
  search_boost = greatest(staging.clothing_type_tags.search_boost, excluded.search_boost),
  updated_at = now();

update staging.clothing_type_tags
set
  mother_category_id = 'jumpsuits',
  updated_at = now()
where id = 'jumpsuit';

with targets as (
  select pp.id
  from staging.product_pages pp
  where ${targetPredicate}
),
upserted_tags as (
  insert into staging.product_page_clothing_type_tags
    (product_page_id, clothing_type_id, evidence)
  select
    id,
    'coverall',
    'Coverall keyword in product page URL/title; user rule maps coverall to jumpsuits primary category.'
  from targets
  on conflict (product_page_id, clothing_type_id) do update set
    evidence = excluded.evidence
  returning product_page_id
),
updated_pages as (
  update staging.product_pages pp
  set
    mother_category_id = 'jumpsuits',
    category_confidence = 'high',
    category_evidence = concat_ws(
      ' ',
      nullif(pp.category_evidence, ''),
      '[taxonomy correction: coverall item tag maps to jumpsuits primary category]'
    ),
    category_source_field = 'manual_coverall_rule',
    category_extractor_version = '${correctionVersion}',
    category_checked_at = now(),
    needs_manual_review = false,
    observed_clothing_type_ids = (
      select array(
        select distinct unnest(coalesce(pp.observed_clothing_type_ids, '{}'::text[]) || array['coverall'])
      )
    ),
    raw_metadata = coalesce(pp.raw_metadata, '{}'::jsonb) || jsonb_build_object(
      'coverall_jumpsuits_category_corrected_at', now(),
      'previous_mother_category_id', pp.mother_category_id,
      'correction_source', '${correctionVersion}'
    ),
    updated_at = now()
  from targets
  where pp.id = targets.id
  returning
    pp.id::text as product_page_id,
    pp.normalized_product_page_url,
    pp.product_title_raw,
    pp.mother_category_id,
    pp.category_confidence
)
select jsonb_build_object(
  'upserted_tag_count', (select count(*) from upserted_tags),
  'updated_page_count', (select count(*) from updated_pages),
  'updated_pages', coalesce((select jsonb_agg(to_jsonb(updated_pages) order by normalized_product_page_url) from updated_pages), '[]'::jsonb)
);

commit;`;

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Coverall taxonomy correction guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const before = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, targetRowsSql), []);
  const applied = apply
    ? (() => {
        requireExplicitWriteFlag();
        return parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, applySql));
      })()
    : {};
  const after = apply ? parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, targetRowsSql), []) : before;

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_coverall_jumpsuits_category_correction_${timestampStem(new Date(generatedAt))}.json`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    correction_version: correctionVersion,
    before_count: before.length,
    before_by_category: summarizeByCategory(before),
    applied,
    after_by_category: summarizeByCategory(after),
    before,
    after,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote coverall taxonomy correction report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Before count: ${report.before_count}`);
  console.log(`Before by category: ${JSON.stringify(report.before_by_category)}`);
  if (apply) {
    console.log(`Updated pages: ${report.applied.updated_page_count || 0}`);
    console.log(`Upserted coverall tags: ${report.applied.upserted_tag_count || 0}`);
    console.log(`After by category: ${JSON.stringify(report.after_by_category)}`);
  } else {
    console.log("Dry-run only. No Supabase rows were written.");
  }
}

function summarizeByCategory(rows) {
  return rows.reduce((summary, row) => {
    const key = row.mother_category_id || "<null>";
    summary[key] = (summary[key] || 0) + 1;
    return summary;
  }, {});
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
