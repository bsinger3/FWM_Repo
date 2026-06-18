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
import { parseWeeksPregnant, PREGNANCY_PARSE_VERSION } from "./lib/pregnancy-parser.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const limit = Math.max(1, Number(parseArg("limit", "500")) || 500);
const FULL_BODY_RESET_VERSION = "full_body_visible_nullable_reset_v1";

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
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

function parseJsonPsql(output, fallback) {
  const trimmed = output.trim();
  return trimmed ? JSON.parse(trimmed) : fallback;
}

function countsSql() {
  return `
select jsonb_build_object(
  'total_images', count(*),
  'full_body_true', count(*) filter (where full_body_visible is true),
  'full_body_false', count(*) filter (where full_body_visible is false),
  'full_body_null', count(*) filter (where full_body_visible is null),
  'full_body_reset_candidates', count(*) filter (where full_body_visible is true and source_file is not null),
  'pregnancy_candidate_rows', count(*) filter (where user_comment is not null and weeks_pregnant is null)
)
from public.images;`;
}

function fullBodyResetSampleSql() {
  return `
select coalesce(jsonb_agg(row_to_json(sample_row) order by sample_row.id), '[]'::jsonb)
from (
  select
    id::text,
    original_url_display,
    source_file,
    source_row_number
  from public.images
  where full_body_visible is true
    and source_file is not null
  order by updated_at desc nulls last, id
  limit 25
) sample_row;`;
}

function pregnancyCandidateSql() {
  return `
select coalesce(jsonb_agg(row_to_json(candidate) order by candidate.id), '[]'::jsonb)
from (
  select
    id::text,
    user_comment
  from public.images
  where user_comment is not null
    and weeks_pregnant is null
  order by updated_at desc nulls last, id
  limit ${limit}
) candidate;`;
}

function pregnancyUpdateSql(rows) {
  if (!rows.length) return "";
  const values = rows
    .map((row) => `(${sqlString(row.id)}::uuid, ${row.weeks_pregnant}::integer, ${sqlString(row.pregnancy_evidence)})`)
    .join(",\n");
  return `
update public.images image
set
  weeks_pregnant = updates.weeks_pregnant,
  pregnancy_evidence = updates.pregnancy_evidence,
  updated_at = now()
from (values
${values}
) as updates(id, weeks_pregnant, pregnancy_evidence)
where image.id = updates.id;`;
}

function applySql(plannedPregnancyUpdates) {
  return `
begin;

update public.images
set
  full_body_visible = null,
  updated_at = now()
where full_body_visible is true
  and source_file is not null;

${pregnancyUpdateSql(plannedPregnancyUpdates)}

commit;`;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Attribute backfill guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const beforeCounts = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, countsSql()), {});
  const fullBodyResetSample = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, fullBodyResetSampleSql()), []);
  const pregnancyCandidates = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, pregnancyCandidateSql()), []);
  const plannedPregnancyUpdates = pregnancyCandidates
    .map((row) => ({ row, parsed: parseWeeksPregnant(row.user_comment) }))
    .filter(({ parsed }) => parsed.weeks_pregnant !== null)
    .map(({ row, parsed }) => ({
      id: row.id,
      weeks_pregnant: parsed.weeks_pregnant,
      pregnancy_evidence: parsed.pregnancy_evidence,
      pregnancy_parse_version: PREGNANCY_PARSE_VERSION,
      comment_preview: String(row.user_comment || "").slice(0, 320),
    }));

  if (apply) {
    requireExplicitWriteFlag();
    runPsql(process.env.DEV_DATABASE_URL, applySql(plannedPregnancyUpdates));
  }

  const afterCounts = apply ? parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, countsSql()), {}) : null;
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const generatedAt = new Date().toISOString();
  const reportPath = path.join(
    reportsDir,
    `dev_image_attribute_backfill_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`,
  );
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    pregnancy_parser_version: PREGNANCY_PARSE_VERSION,
    full_body_reset_version: FULL_BODY_RESET_VERSION,
    limit,
    before_counts: beforeCounts,
    after_counts: afterCounts,
    planned_full_body_visible_reset_count: Number(beforeCounts.full_body_reset_candidates || 0),
    full_body_visible_reset_policy:
      "Reset loader-populated true values with source_file provenance to null because head-and-feet visibility has not been conservatively proven.",
    full_body_reset_sample: fullBodyResetSample,
    pregnancy_candidate_rows_scanned: pregnancyCandidates.length,
    planned_weeks_pregnant_updates: plannedPregnancyUpdates.length,
    sample_weeks_pregnant_updates: plannedPregnancyUpdates.slice(0, 25),
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote attribute backfill report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Planned full_body_visible resets: ${report.planned_full_body_visible_reset_count}`);
  console.log(`Candidate pregnancy rows scanned: ${pregnancyCandidates.length}`);
  console.log(`Planned weeks_pregnant updates: ${plannedPregnancyUpdates.length}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
