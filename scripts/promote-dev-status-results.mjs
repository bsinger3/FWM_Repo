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
const statusReportPath = parseArg("status-report");
const verifiedReportPath = parseArg("verified-report");

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
  return Number.isFinite(Number(value)) ? String(Number(value)) : "null";
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

async function requireStatusReport() {
  if (!statusReportPath) {
    throw new Error(
      "Usage: npm run dev-images:status:promote -- --status-report=/absolute/path/report.json --verified-report=/absolute/path/verify.json [--apply]",
    );
  }
  const resolved = path.resolve(statusReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.mode !== "dry-run" || !report.checker_version) {
    throw new Error(`Status report is not a status dry-run report: ${resolved}`);
  }
  return { resolved, report };
}

async function requirePassedVerificationReport(expectedStatusReportPath) {
  if (!verifiedReportPath) {
    throw new Error("Promotion requires --verified-report=/absolute/path/dev_refresh_report_verify_status_*.json.");
  }
  const resolved = path.resolve(verifiedReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.report_type !== "status" || report.passed !== true) {
    throw new Error(`Verification report did not pass for status: ${resolved}`);
  }
  if (path.resolve(report.report_path) !== path.resolve(expectedStatusReportPath)) {
    throw new Error(
      `Verification report points to ${report.report_path}, not status report ${expectedStatusReportPath}.`,
    );
  }
  return { resolved, report };
}

function plannedPromotions(statusReport) {
  return (statusReport.results || [])
    .filter((result) => result.product_page_id)
    .map((result) => ({
      product_page_id: result.product_page_id,
      normalized_product_page_url: result.normalized_product_page_url,
      source_status: result.source_status,
      source_status_checked_at: result.source_status_checked_at,
      source_http_status: result.source_http_status,
      source_final_url: result.source_final_url,
      source_redirected: result.source_redirected,
      source_final_url_type: result.source_final_url_type,
      source_status_evidence: result.source_status_evidence,
      source_status_error: result.source_status_error,
      source_status_checker_version: result.source_status_checker_version,
      robots_disallowed: result.robots_disallowed,
    }));
}

function humanReviewRows(rows) {
  const reviewStatuses = new Set(["robots_disallowed", "blocked_or_forbidden", "timeout", "unknown", "redirected_to_non_product"]);
  return rows
    .filter((row) => reviewStatuses.has(row.source_status))
    .map((row) => ({
      product_page_id: row.product_page_id,
      normalized_product_page_url: row.normalized_product_page_url,
      source_status: row.source_status,
      source_final_url_type: row.source_final_url_type,
      source_status_evidence: row.source_status_evidence,
      source_status_error: row.source_status_error,
      robots_disallowed: row.robots_disallowed,
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

function summarize(rows, humanReview) {
  const byStatus = {};
  for (const row of rows) byStatus[row.source_status] = (byStatus[row.source_status] || 0) + 1;
  const humanReviewByStatus = {};
  for (const row of humanReview) humanReviewByStatus[row.source_status] = (humanReviewByStatus[row.source_status] || 0) + 1;
  return { planned_by_status: byStatus, human_review_by_status: humanReviewByStatus };
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function buildHumanReviewCsv(rows) {
  const headers = [
    "product_page_id",
    "normalized_product_page_url",
    "source_status",
    "source_final_url_type",
    "source_status_evidence",
    "source_status_error",
    "robots_disallowed",
  ];
  return [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n") + "\n";
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Status promotion guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const { resolved: resolvedStatusReportPath, report: statusReport } = await requireStatusReport();
  const { resolved: resolvedVerifiedReportPath } = await requirePassedVerificationReport(resolvedStatusReportPath);
  const planned = plannedPromotions(statusReport);
  const humanReview = humanReviewRows(planned);

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportStem = `dev_status_promotion_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const reportPath = path.join(reportsDir, `${reportStem}.json`);
  const humanReviewCsvPath = path.join(reportsDir, `${reportStem}_human_review.csv`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    status_report_path: resolvedStatusReportPath,
    verified_report_path: resolvedVerifiedReportPath,
    planned_update_count: planned.length,
    human_review_count: humanReview.length,
    human_review_csv_path: humanReviewCsvPath,
    summary: summarize(planned, humanReview),
    planned_updates: planned,
    human_review_rows: humanReview,
  };

  if (apply) {
    requireExplicitWriteFlag();
    if (planned.length) runPsql(process.env.DEV_DATABASE_URL, updateSql(planned));
  }

  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(humanReviewCsvPath, buildHumanReviewCsv(humanReview), "utf8");
  console.log(`Wrote status promotion report: ${reportPath}`);
  console.log(`Wrote status promotion human-review CSV: ${humanReviewCsvPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Planned updates: ${planned.length}`);
  console.log(`Human-review rows: ${humanReview.length}`);
  console.log(`Summary: ${JSON.stringify(report.summary)}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
