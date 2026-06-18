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
const orientationReportPath = parseArg("orientation-report");
const verifiedReportPath = parseArg("verified-report");
const allowedConfidence = new Set(
  String(parseArg("allowed-confidence", "high"))
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

function sqlJson(value) {
  return `${sqlString(JSON.stringify(value ?? null))}::jsonb`;
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

async function requireOrientationReport() {
  if (!orientationReportPath) {
    throw new Error(
      "Usage: npm run dev-images:orientation:promote -- --orientation-report=/absolute/path/report.json --verified-report=/absolute/path/verify.json [--apply]",
    );
  }
  const resolved = path.resolve(orientationReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.mode !== "dry-run" || !report.orientation_model_version) {
    throw new Error(`Orientation report is not an orientation dry-run report: ${resolved}`);
  }
  return { resolved, report };
}

async function requirePassedVerificationReport(expectedOrientationReportPath) {
  if (!verifiedReportPath) {
    throw new Error("Promotion requires --verified-report=/absolute/path/dev_refresh_report_verify_orientation_*.json.");
  }
  const resolved = path.resolve(verifiedReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.report_type !== "orientation" || report.passed !== true) {
    throw new Error(`Verification report did not pass for orientation: ${resolved}`);
  }
  if (path.resolve(report.report_path) !== path.resolve(expectedOrientationReportPath)) {
    throw new Error(
      `Verification report points to ${report.report_path}, not orientation report ${expectedOrientationReportPath}.`,
    );
  }
  return { resolved, report };
}

function mergeCropSpecWithRotation(currentCropSpec, rotationDeg) {
  const base = currentCropSpec && typeof currentCropSpec === "object" ? { ...currentCropSpec } : {};
  return {
    mode: base.mode || "object-position",
    aspectRatio: base.aspectRatio || base.aspect_ratio || "3:4",
    objectPositionXPct: Number.isFinite(Number(base.objectPositionXPct ?? base.object_position_x_pct))
      ? Number(base.objectPositionXPct ?? base.object_position_x_pct)
      : 50,
    objectPositionYPct: Number.isFinite(Number(base.objectPositionYPct ?? base.object_position_y_pct))
      ? Number(base.objectPositionYPct ?? base.object_position_y_pct)
      : 50,
    zoom: Number.isFinite(Number(base.zoom ?? base.crop_zoom)) ? Number(base.zoom ?? base.crop_zoom) : 1,
    rotationDeg,
    source: base.source || "orientation_audit",
  };
}

function plannedPromotions(orientationReport) {
  return (orientationReport.results || [])
    .filter((result) => result.proposed_database_write)
    .filter((result) => allowedConfidence.has(result.proposed?.confidence))
    .map((result) => {
      const rotationDeg = Number(result.proposed.proposed_rotation_deg);
      return {
        image_id: result.image_id,
        image_url: result.image_url,
        proposed_rotation_deg: rotationDeg,
        crop_spec: mergeCropSpecWithRotation(result.current_crop_spec, rotationDeg),
        image_orientation_degrees: rotationDeg,
        image_orientation_confidence: result.proposed.confidence,
        image_orientation_evidence: result.proposed.evidence,
        image_orientation_model_version: orientationReport.orientation_model_version,
      };
    });
}

function skippedRows(orientationReport, planned) {
  const plannedIds = new Set(planned.map((row) => row.image_id));
  return (orientationReport.results || [])
    .filter((result) => result.skipped || result.proposed_database_write)
    .filter((result) => !plannedIds.has(result.image_id))
    .map((result) => ({
      image_id: result.image_id,
      image_url: result.image_url,
      skipped_in_audit: Boolean(result.skipped),
      audit_skip_reason: result.skip_reason || null,
      proposed_rotation_deg: result.proposed?.proposed_rotation_deg ?? null,
      confidence: result.proposed?.confidence || null,
      skip_reason: result.skipped
        ? "audit_skipped"
        : !allowedConfidence.has(result.proposed?.confidence)
          ? "confidence_not_allowed"
          : "no_allowed_orientation_update",
    }));
}

function updateSql(rows) {
  const statements = rows.map((row) => `
update public.images
set
  crop_spec = ${sqlJson(row.crop_spec)},
  image_orientation_degrees = ${row.image_orientation_degrees},
  image_orientation_confidence = ${sqlString(row.image_orientation_confidence)},
  image_orientation_evidence = ${sqlJson(row.image_orientation_evidence)},
  image_orientation_checked_at = now(),
  image_orientation_model_version = ${sqlString(row.image_orientation_model_version)},
  updated_at = now()
where id = ${sqlString(row.image_id)}::uuid;`);
  return `begin;\n${statements.join("\n")}\ncommit;`;
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function buildSkippedRowsCsv(rows) {
  const headers = [
    "image_id",
    "image_url",
    "skip_reason",
    "audit_skip_reason",
    "proposed_rotation_deg",
    "confidence",
  ];
  return [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n") + "\n";
}

function summarize(rows, skipped) {
  const byRotation = {};
  for (const row of rows) byRotation[row.proposed_rotation_deg] = (byRotation[row.proposed_rotation_deg] || 0) + 1;
  const skippedByReason = {};
  for (const row of skipped) skippedByReason[row.skip_reason] = (skippedByReason[row.skip_reason] || 0) + 1;
  return { planned_by_rotation: byRotation, skipped_by_reason: skippedByReason };
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Orientation promotion guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const { resolved: resolvedOrientationReportPath, report: orientationReport } = await requireOrientationReport();
  const { resolved: resolvedVerifiedReportPath } = await requirePassedVerificationReport(resolvedOrientationReportPath);
  const planned = plannedPromotions(orientationReport);
  const skipped = skippedRows(orientationReport, planned);

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportStem = `dev_orientation_promotion_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const reportPath = path.join(reportsDir, `${reportStem}.json`);
  const skippedRowsCsvPath = path.join(reportsDir, `${reportStem}_skipped_rows.csv`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    orientation_report_path: resolvedOrientationReportPath,
    verified_report_path: resolvedVerifiedReportPath,
    allowed_confidence: Array.from(allowedConfidence),
    planned_update_count: planned.length,
    skipped_count: skipped.length,
    skipped_rows_csv_path: skippedRowsCsvPath,
    summary: summarize(planned, skipped),
    planned_updates: planned,
    skipped_rows: skipped,
  };

  if (apply) {
    requireExplicitWriteFlag();
    if (planned.length) runPsql(process.env.DEV_DATABASE_URL, updateSql(planned));
  }

  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(skippedRowsCsvPath, buildSkippedRowsCsv(skipped), "utf8");
  console.log(`Wrote orientation promotion report: ${reportPath}`);
  console.log(`Wrote orientation promotion skipped-rows CSV: ${skippedRowsCsvPath}`);
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
