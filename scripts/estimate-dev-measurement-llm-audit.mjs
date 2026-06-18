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
const sampleSize = Math.max(1, Number(parseArg("sample-size", "100")) || 100);
const minCommentChars = Math.max(1, Number(parseArg("min-comment-chars", "40")) || 40);
const model = parseArg("model", "set-by-approval");
const fixedPromptTokens = Math.max(0, Number(parseArg("fixed-prompt-tokens", "900")) || 900);
const perRowOverheadTokens = Math.max(0, Number(parseArg("per-row-overhead-tokens", "60")) || 60);
const expectedOutputTokensPerRow = Math.max(0, Number(parseArg("expected-output-tokens-per-row", "120")) || 120);
const inputPricePer1m = numberOrNull(parseArg("input-price-per-1m"));
const outputPricePer1m = numberOrNull(parseArg("output-price-per-1m"));
const pricingSource = parseArg("pricing-source", "");
const pricingDate = parseArg("pricing-date", "");
const ESTIMATOR_VERSION = "measurement_llm_audit_cost_estimator_v1";

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
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

function parseJsonPsql(output) {
  const trimmed = output.trim();
  return trimmed ? JSON.parse(trimmed) : [];
}

function candidateWhere() {
  return `
    user_comment is not null
    and length(btrim(user_comment)) >= ${minCommentChars}
    and (
      height_in_display is null
      or weight_display_display is null
      or waist_in is null
      or hips_in_display is null
      or bust_in_number_display is null
      or cupsize_display is null
      or inseam_inches_display is null
    )`;
}

function strataSql() {
  return `
select coalesce(jsonb_agg(row_to_json(stratum) order by stratum.row_count desc), '[]'::jsonb)
from (
  select
    coalesce(nullif(source_site_display, ''), 'unknown') as source_site,
    count(*)::integer as row_count,
    round(avg(length(user_comment)))::integer as avg_comment_chars
  from public.images
  where ${candidateWhere()}
  group by 1
  order by row_count desc
) stratum;`;
}

function sampleSql() {
  return `
select coalesce(jsonb_agg(row_to_json(sample_row)), '[]'::jsonb)
from (
  select
    id::text,
    coalesce(nullif(source_site_display, ''), 'unknown') as source_site,
    user_comment,
    height_in_display,
    weight_display_display,
    waist_in,
    hips_in_display,
    bust_in_number_display,
    cupsize_display,
    inseam_inches_display
  from public.images
  where ${candidateWhere()}
  order by random()
  limit ${sampleSize}
) sample_row;`;
}

function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[index];
}

function estimateTokens(text) {
  return Math.ceil(String(text || "").length / 4);
}

function summarizeSample(rows) {
  const tokenCounts = rows.map((row) => estimateTokens(row.user_comment)).sort((a, b) => a - b);
  const bySource = {};
  for (const row of rows) {
    bySource[row.source_site] = (bySource[row.source_site] || 0) + 1;
  }
  return {
    sampled_rows: rows.length,
    avg_comment_tokens: tokenCounts.length
      ? Math.round(tokenCounts.reduce((sum, value) => sum + value, 0) / tokenCounts.length)
      : 0,
    p90_comment_tokens: percentile(tokenCounts, 90),
    max_comment_tokens: tokenCounts.at(-1) || 0,
    sample_rows_by_source_site: bySource,
  };
}

function estimateCost({ targetRows, avgCommentTokens }) {
  const estimatedInputTokens =
    fixedPromptTokens + targetRows * (avgCommentTokens + perRowOverheadTokens);
  const estimatedOutputTokens = targetRows * expectedOutputTokensPerRow;
  if (inputPricePer1m === null || outputPricePer1m === null) {
    return {
      pricing_complete: false,
      pricing_required: "Provide --input-price-per-1m, --output-price-per-1m, --pricing-source, and --pricing-date from current published model pricing before approval.",
      estimated_input_tokens: estimatedInputTokens,
      estimated_output_tokens: estimatedOutputTokens,
      estimated_total_cost_usd: null,
    };
  }
  return {
    pricing_complete: true,
    estimated_input_tokens: estimatedInputTokens,
    estimated_output_tokens: estimatedOutputTokens,
    estimated_input_cost_usd: (estimatedInputTokens / 1_000_000) * inputPricePer1m,
    estimated_output_cost_usd: (estimatedOutputTokens / 1_000_000) * outputPricePer1m,
    estimated_total_cost_usd:
      (estimatedInputTokens / 1_000_000) * inputPricePer1m +
      (estimatedOutputTokens / 1_000_000) * outputPricePer1m,
  };
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Measurement LLM audit estimator guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const strata = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, strataSql()));
  const sampleRows = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, sampleSql()));
  const sampleSummary = summarizeSample(sampleRows);
  const targetRows = strata.reduce((sum, stratum) => sum + Number(stratum.row_count || 0), 0);
  const cost = estimateCost({
    targetRows,
    avgCommentTokens: sampleSummary.avg_comment_tokens,
  });

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_measurement_llm_audit_estimate_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`);
  const report = {
    generated_at: generatedAt,
    mode: "estimate-only-no-llm",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    estimator_version: ESTIMATOR_VERSION,
    llm_rows_sent: 0,
    approval_required_before_llm_run: true,
    candidate_filter: {
      min_comment_chars: minCommentChars,
      requires_user_comment: true,
      missing_any_measurement_field: [
        "height_in_display",
        "weight_display_display",
        "waist_in",
        "hips_in_display",
        "bust_in_number_display",
        "cupsize_display",
        "inseam_inches_display",
      ],
    },
    model,
    pricing: {
      input_price_per_1m_tokens_usd: inputPricePer1m,
      output_price_per_1m_tokens_usd: outputPricePer1m,
      pricing_source: pricingSource || null,
      pricing_date: pricingDate || null,
    },
    fixed_prompt_tokens: fixedPromptTokens,
    per_row_overhead_tokens: perRowOverheadTokens,
    expected_output_tokens_per_row: expectedOutputTokensPerRow,
    target_candidate_rows: targetRows,
    source_site_strata: strata,
    sample_summary: sampleSummary,
    cost_estimate: cost,
    sample_rows: sampleRows.map((row) => ({
      ...row,
      estimated_comment_tokens: estimateTokens(row.user_comment),
      user_comment_preview: String(row.user_comment || "").slice(0, 500),
      user_comment: undefined,
    })),
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(`Wrote measurement LLM audit estimate report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Candidate rows: ${targetRows}`);
  console.log(`Sample rows: ${sampleSummary.sampled_rows}`);
  console.log(`Avg/p90 comment tokens: ${sampleSummary.avg_comment_tokens}/${sampleSummary.p90_comment_tokens}`);
  console.log(`Estimated input/output tokens: ${cost.estimated_input_tokens}/${cost.estimated_output_tokens}`);
  console.log(`Estimated cost: ${cost.estimated_total_cost_usd === null ? "pricing required" : `$${cost.estimated_total_cost_usd.toFixed(4)}`}`);
  console.log("No rows were sent to an LLM.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
