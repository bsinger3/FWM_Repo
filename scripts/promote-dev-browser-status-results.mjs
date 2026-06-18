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
const browserReportPath = parseArg("browser-report");
const verifiedReportPath = parseArg("verified-report");
const allowedStatuses = new Set(
  String(parseArg("allowed-statuses", "live,out_of_stock,page_not_found,product_unavailable,redirected_to_product,redirected_to_non_product"))
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlBoolean(value) {
  if (value === null || value === undefined) return "null";
  return value ? "true" : "false";
}

function sqlNumber(value) {
  return Number.isFinite(value) ? String(value) : "null";
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

async function requireBrowserReport() {
  if (!browserReportPath) {
    throw new Error("Usage: npm run dev-images:browser-status:promote -- --browser-report=/absolute/path/report.json --verified-report=/absolute/path/verify.json [--apply]");
  }
  const resolved = path.resolve(browserReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.mode !== "dry-run" || !report.browser_checker_version) {
    throw new Error(`Browser report is not a browser-status dry-run report: ${resolved}`);
  }
  return { resolved, report };
}

async function requirePassedVerificationReport(expectedBrowserReportPath) {
  if (!verifiedReportPath) {
    throw new Error("Promotion requires --verified-report=/absolute/path/dev_refresh_report_verify_browser-status_*.json.");
  }
  const resolved = path.resolve(verifiedReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.report_type !== "browser-status" || report.passed !== true) {
    throw new Error(`Verification report did not pass for browser-status: ${resolved}`);
  }
  if (path.resolve(report.report_path) !== path.resolve(expectedBrowserReportPath)) {
    throw new Error(
      `Verification report points to ${report.report_path}, not browser report ${expectedBrowserReportPath}.`,
    );
  }
  return { resolved, report };
}

function plannedPromotions(browserReport) {
  return (browserReport.results || [])
    .filter((result) => allowedStatuses.has(result.browser_status))
    .filter((result) => !result.human_review_reason)
    .filter((result) => result.product_page_id)
    .map((result) => ({
      product_page_id: result.product_page_id,
      normalized_product_page_url: result.normalized_product_page_url,
      previous_source_status: result.previous_source_status,
      source_status: result.browser_status,
      source_status_checked_at: result.browser_checked_at,
      source_http_status: result.browser_http_status,
      source_final_url: result.browser_final_url,
      source_redirected:
        Boolean(result.browser_final_url) &&
        Boolean(result.normalized_product_page_url) &&
        result.browser_final_url.replace(/\/+$/, "") !== result.normalized_product_page_url.replace(/\/+$/, ""),
      source_final_url_type: result.browser_final_url_type,
      source_status_evidence: result.browser_status_evidence,
      source_status_error: result.browser_status_error || null,
      source_status_checker_version: result.browser_checker_version,
      robots_disallowed: false,
      screenshot_path: result.screenshot_path || null,
    }));
}

function skippedRows(browserReport, planned) {
  const plannedIds = new Set(planned.map((row) => row.product_page_id));
  return (browserReport.results || [])
    .filter((result) => !plannedIds.has(result.product_page_id))
    .map((result) => ({
      product_page_id: result.product_page_id,
      normalized_product_page_url: result.normalized_product_page_url,
      browser_status: result.browser_status,
      human_review_reason: result.human_review_reason || null,
      skip_reason: result.human_review_reason
        ? "human_review"
        : !allowedStatuses.has(result.browser_status)
          ? "status_not_allowed_for_promotion"
          : "missing_product_page_id_or_unknown",
    }));
}

function updateSql(rows) {
  const updates = rows.map((row) => `
update staging.product_pages
set
  source_status = ${sqlString(row.source_status)},
  source_status_checked_at = ${sqlString(row.source_status_checked_at)}::timestamptz,
  source_http_status = ${sqlNumber(row.source_http_status)},
  source_final_url = ${sqlString(row.source_final_url)},
  source_redirected = ${sqlBoolean(row.source_redirected)},
  source_final_url_type = ${sqlString(row.source_final_url_type)},
  source_status_evidence = ${sqlString(row.source_status_evidence)},
  source_status_error = ${sqlString(row.source_status_error)},
  source_status_checker_version = ${sqlString(row.source_status_checker_version)},
  robots_disallowed = ${sqlBoolean(row.robots_disallowed)}
where id = ${sqlString(row.product_page_id)}::uuid;`);
  return `begin;\n${updates.join("\n")}\ncommit;`;
}

function summarize(rows, skipped) {
  const byStatus = {};
  for (const row of rows) byStatus[row.source_status] = (byStatus[row.source_status] || 0) + 1;
  const skippedByReason = {};
  for (const row of skipped) skippedByReason[row.skip_reason] = (skippedByReason[row.skip_reason] || 0) + 1;
  return { planned_by_status: byStatus, skipped_by_reason: skippedByReason };
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Browser status promotion guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const { resolved: resolvedBrowserReportPath, report: browserReport } = await requireBrowserReport();
  const { resolved: resolvedVerifiedReportPath } = await requirePassedVerificationReport(resolvedBrowserReportPath);
  const planned = plannedPromotions(browserReport);
  const skipped = skippedRows(browserReport, planned);

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_browser_status_promotion_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    browser_report_path: resolvedBrowserReportPath,
    verified_report_path: resolvedVerifiedReportPath,
    allowed_statuses: Array.from(allowedStatuses),
    planned_update_count: planned.length,
    skipped_count: skipped.length,
    summary: summarize(planned, skipped),
    planned_updates: planned,
    skipped_rows: skipped,
  };

  if (apply) {
    requireExplicitWriteFlag();
    if (planned.length) runPsql(process.env.DEV_DATABASE_URL, updateSql(planned));
  }

  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(`Wrote browser status promotion report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Planned updates: ${planned.length}`);
  console.log(`Skipped rows: ${skipped.length}`);
  console.log(`Summary: ${JSON.stringify(report.summary)}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
