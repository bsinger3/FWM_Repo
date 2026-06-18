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
  const trimmed = output.trim();
  return trimmed ? JSON.parse(trimmed) : {};
}

function parseIntegerPsql(output) {
  const numericLine = String(output || "")
    .trim()
    .split(/\r?\n/)
    .map((line) => line.trim())
    .reverse()
    .find((line) => /^\d+$/.test(line));
  return Number(numericLine || 0);
}

const targetRowsCte = `
with tagged as (
  select
    pp.id,
    pp.normalized_product_page_url,
    pp.mother_category_id as current_mother_category_id,
    pp.category_evidence,
    pp.product_title_raw,
    pp.product_category_raw,
    bool_or(pct.clothing_type_id = 'romper') as has_romper,
    bool_or(pct.clothing_type_id = 'jumpsuit') as has_jumpsuit,
    string_agg(distinct pct.evidence, ' | ') filter (where pct.clothing_type_id in ('romper', 'jumpsuit')) as tag_evidence
  from staging.product_pages pp
  join staging.product_page_clothing_type_tags pct
    on pct.product_page_id = pp.id
   and pct.clothing_type_id in ('romper', 'jumpsuit')
  where pp.mother_category_id = 'dresses'
  group by
    pp.id,
    pp.normalized_product_page_url,
    pp.mother_category_id,
    pp.category_evidence,
    pp.product_title_raw,
    pp.product_category_raw
),
classified as (
  select
    *,
    case
      when has_romper and not has_jumpsuit then 'romper'
      when has_jumpsuit and not has_romper then 'jumpsuit'
      when has_romper
        and concat_ws(' ', product_title_raw, product_category_raw, normalized_product_page_url, category_evidence, tag_evidence)
          ~* '\\m(romper|rompers|playsuit|playsuits|play suit|play suits)\\M'
        then 'romper'
      when has_jumpsuit
        and concat_ws(' ', product_title_raw, product_category_raw, normalized_product_page_url, category_evidence, tag_evidence)
          ~* '\\m(jumpsuit|jumpsuits|jump suit|jump suits)\\M'
        then 'jumpsuit'
      else null
    end as target_mother_category_id
  from tagged
)`;

const summarySql = `
${targetRowsCte},
counts as (
  select target_mother_category_id, count(*) as target_count
  from classified
  where target_mother_category_id is not null
  group by target_mother_category_id
)
select jsonb_build_object(
  'mode', ${apply ? "'apply'" : "'dry-run'"},
  'total_dresses_with_romper_or_jumpsuit_tag', (select count(*) from classified),
  'planned_update_count', (select count(*) from classified where target_mother_category_id is not null),
  'ambiguous_count', (select count(*) from classified where target_mother_category_id is null),
  'planned_by_target_category', coalesce((
    select jsonb_object_agg(target_mother_category_id, target_count)
    from counts
  ), '{}'::jsonb),
  'ambiguous_samples', coalesce((
    select jsonb_agg(to_jsonb(sample) order by sample.normalized_product_page_url)
    from (
      select
        id::text as product_page_id,
        normalized_product_page_url,
        has_romper,
        has_jumpsuit,
        left(coalesce(tag_evidence, ''), 300) as tag_evidence
      from classified
      where target_mother_category_id is null
      order by normalized_product_page_url
      limit 25
    ) sample
  ), '[]'::jsonb),
  'planned_samples', coalesce((
    select jsonb_agg(to_jsonb(sample) order by sample.normalized_product_page_url)
    from (
      select
        id::text as product_page_id,
        normalized_product_page_url,
        current_mother_category_id,
        target_mother_category_id,
        has_romper,
        has_jumpsuit,
        left(coalesce(tag_evidence, ''), 300) as tag_evidence
      from classified
      where target_mother_category_id is not null
      order by normalized_product_page_url
      limit 50
    ) sample
  ), '[]'::jsonb)
);`;

const applySql = `
begin;

insert into staging.clothing_mother_categories
  (id, label, display_label, sort_order, frontend_sort_order, is_frontend_filter)
values
  ('jumpsuit', 'Jumpsuit', 'Jumpsuit', 35, 35, true),
  ('romper', 'Romper', 'Romper', 36, 36, true)
on conflict (id) do update set
  label = excluded.label,
  display_label = excluded.display_label,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  is_frontend_filter = excluded.is_frontend_filter,
  updated_at = now();

update staging.clothing_type_tags
set
  mother_category_id = case id
    when 'jumpsuit' then 'jumpsuit'
    when 'romper' then 'romper'
  end,
  sort_order = 10,
  frontend_sort_order = 10,
  search_boost = greatest(search_boost, 1.4),
  updated_at = now()
where id in ('jumpsuit', 'romper');

${targetRowsCte},
updates as (
  update staging.product_pages pp
  set
    mother_category_id = classified.target_mother_category_id,
    category_evidence = concat_ws(
      ' ',
      nullif(pp.category_evidence, ''),
      '[taxonomy correction: romper and jumpsuit are standalone primary categories]'
    ),
    category_extractor_version = coalesce(pp.category_extractor_version, 'manual_taxonomy_correction_v1'),
    category_checked_at = now(),
    raw_metadata = pp.raw_metadata || jsonb_build_object(
      'romper_jumpsuit_category_corrected_at', now(),
      'previous_mother_category_id', pp.mother_category_id,
      'correction_source', 'fix-dev-romper-jumpsuit-categories'
    ),
    updated_at = now()
  from classified
  where pp.id = classified.id
    and classified.target_mother_category_id is not null
  returning pp.id
)
select count(*)::integer from updates;

commit;`;

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Romper/jumpsuit taxonomy correction guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const summary = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, summarySql));
  if (apply) {
    requireExplicitWriteFlag();
    summary.applied_update_count = parseIntegerPsql(runPsql(process.env.DEV_DATABASE_URL, applySql));
  }

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_taxonomy_romper_jumpsuit_category_fix_${timestampStem(new Date(generatedAt))}.json`);
  const report = {
    generated_at: generatedAt,
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    ...summary,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote romper/jumpsuit taxonomy correction report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Planned updates: ${report.planned_update_count}`);
  console.log(`Ambiguous skipped: ${report.ambiguous_count}`);
  console.log(`By target category: ${JSON.stringify(report.planned_by_target_category)}`);
  if (apply) console.log(`Applied updates: ${report.applied_update_count}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
