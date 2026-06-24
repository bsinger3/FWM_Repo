#!/usr/bin/env node

import { access, readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  DEV_SUPABASE_REF,
  DEV_SUPABASE_URL,
  assertApprovedDevSupabase,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const reportPath = parseArg("report");
const reportType = parseArg("type");

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function ok(name, condition, details = null) {
  return { name, ok: Boolean(condition), details };
}

async function exists(filePath) {
  if (!filePath) return false;
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

function verifyTarget(report) {
  return [
    ok("report_points_to_dev_url", report.supabase_url === DEV_SUPABASE_URL, report.supabase_url),
    ok("report_points_to_dev_ref", report.supabase_project_ref === DEV_SUPABASE_REF, report.supabase_project_ref),
  ];
}

function proposedTaxonomyEntries(result) {
  const primary = result.proposed?.primaryCategory;
  return [
    ...(primary ? [{
      type: "primary_category",
      source_field: primary.category_source_field,
      evidence: primary.category_evidence,
    }] : []),
    ...(result.proposed?.itemTags || []).map((tag) => ({ type: "item_tag", ...tag })),
    ...(result.proposed?.attributeTags || []).map((tag) => ({ type: "attribute_tag", ...tag })),
  ];
}

async function verifyTaxonomy(report) {
  const checks = [
    ...verifyTarget(report),
    ok("taxonomy_has_extractor_version", Boolean(report.extractor_version), report.extractor_version),
    ok("taxonomy_is_dry_run_or_apply", ["dry-run", "apply"].includes(report.mode), report.mode),
    ok("taxonomy_has_results", Array.isArray(report.results), report.results?.length),
    ok("taxonomy_has_summary", Boolean(report.summary), report.summary),
    ok("taxonomy_review_html_exists", await exists(report.review_html_path), report.review_html_path),
    ok("taxonomy_human_review_csv_exists", await exists(report.human_review_csv_path), report.human_review_csv_path),
    ok("taxonomy_reports_human_review_count", Number.isFinite(Number(report.human_review_count)), report.human_review_count),
  ];

  let proposedTagCount = 0;
  let missingEvidence = 0;
  let missingSourceField = 0;
  let urlFallbackProposedCount = 0;
  let urlFallbackGuardFailures = 0;
  let urlFallbackNonSlugEvidence = 0;
  for (const result of report.results || []) {
    const primary = result.proposed?.primaryCategory;
    if (primary) {
      proposedTagCount += 1;
      if (!primary.category_evidence) missingEvidence += 1;
      if (!primary.category_source_field) missingSourceField += 1;
    }
    for (const tag of result.proposed?.itemTags || []) {
      proposedTagCount += 1;
      if (!tag.evidence) missingEvidence += 1;
      if (!tag.source_field) missingSourceField += 1;
    }
    for (const tag of result.proposed?.attributeTags || []) {
      proposedTagCount += 1;
      if (!tag.evidence) missingEvidence += 1;
      if (!tag.source_field) missingSourceField += 1;
    }
    const entries = proposedTaxonomyEntries(result);
    if (result.skip_reason === "robots_url_fallback" && entries.length) {
      urlFallbackProposedCount += 1;
      if (result.url_fallback_guard?.passed !== true) urlFallbackGuardFailures += 1;
      if (entries.some((entry) => entry.source_field !== "url_slug")) urlFallbackNonSlugEvidence += 1;
    }
  }

  checks.push(ok("taxonomy_proposed_tags_have_evidence", missingEvidence === 0, { proposedTagCount, missingEvidence }));
  checks.push(ok("taxonomy_proposed_tags_have_source_fields", missingSourceField === 0, { proposedTagCount, missingSourceField }));
  checks.push(ok("taxonomy_url_fallback_guard_passed_for_proposals", urlFallbackGuardFailures === 0, { urlFallbackProposedCount, urlFallbackGuardFailures }));
  checks.push(ok("taxonomy_url_fallback_uses_only_url_slug_evidence", urlFallbackNonSlugEvidence === 0, { urlFallbackProposedCount, urlFallbackNonSlugEvidence }));
  checks.push(ok("taxonomy_reports_workbook_disagreements", "workbook_disagreements" in (report.summary || {}), report.summary?.workbook_disagreements));
  return checks;
}

async function verifyOrientation(report) {
  const checks = [
    ...verifyTarget(report),
    ok("orientation_has_model_version", Boolean(report.orientation_model_version), report.orientation_model_version),
    ok("orientation_is_dry_run_or_apply", ["dry-run", "apply"].includes(report.mode), report.mode),
    ok("orientation_has_results", Array.isArray(report.results), report.results?.length),
    ok("orientation_has_summary", Boolean(report.summary), report.summary),
    ok("orientation_review_html_exists", await exists(report.review_html_path), report.review_html_path),
    ok("orientation_review_csv_exists", await exists(report.review_csv_path), report.review_csv_path),
    ok("orientation_reports_review_csv_count", Number.isFinite(Number(report.review_csv_row_count)), report.review_csv_row_count),
  ];

  let malformedRotation = 0;
  let missingEvidenceForWrite = 0;
  for (const result of report.results || []) {
    const rotation = result.proposed?.proposed_rotation_deg;
    if (rotation !== undefined && ![0, 90, 180, 270].includes(Number(rotation))) malformedRotation += 1;
    if (result.proposed_database_write && !result.proposed?.evidence) missingEvidenceForWrite += 1;
  }
  checks.push(ok("orientation_rotations_are_allowed_values", malformedRotation === 0, { malformedRotation }));
  checks.push(ok("orientation_writes_have_evidence", missingEvidenceForWrite === 0, { missingEvidenceForWrite }));
  return checks;
}

async function verifyStatus(report) {
  const checks = [
    ...verifyTarget(report),
    ok("status_has_checker_version", Boolean(report.checker_version), report.checker_version),
    ok("status_is_dry_run_or_apply", ["dry-run", "apply"].includes(report.mode), report.mode),
    ok("status_has_results", Array.isArray(report.results), report.results?.length),
    ok("status_has_counts", Boolean(report.status_counts), report.status_counts),
    ok("status_review_html_exists", await exists(report.review_html_path), report.review_html_path),
    ok("status_reports_robots_by_domain", Boolean(report.robots_disallowed_by_domain), report.robots_disallowed_by_domain),
  ];

  let missingEvidence = 0;
  let missingCheckerVersion = 0;
  let malformedFinalUrlType = 0;
  const allowedFinalUrlTypes = new Set(["product", "non_product", "blocked", "unknown"]);
  for (const result of report.results || []) {
    if (!result.source_status_evidence) missingEvidence += 1;
    if (!result.source_status_checker_version) missingCheckerVersion += 1;
    if (!allowedFinalUrlTypes.has(result.source_final_url_type)) malformedFinalUrlType += 1;
  }
  checks.push(ok("status_results_have_evidence", missingEvidence === 0, { missingEvidence }));
  checks.push(ok("status_results_have_checker_version", missingCheckerVersion === 0, { missingCheckerVersion }));
  checks.push(ok("status_final_url_types_are_allowed", malformedFinalUrlType === 0, { malformedFinalUrlType }));
  return checks;
}

async function verifyBrowserStatus(report) {
  const checks = [
    ...verifyTarget(report),
    ok("browser_status_has_checker_version", Boolean(report.browser_checker_version), report.browser_checker_version),
    ok("browser_status_is_dry_run_only", report.mode === "dry-run", report.mode),
    ok("browser_status_has_results", Array.isArray(report.results), report.results?.length),
    ok("browser_status_has_summary", Boolean(report.summary), report.summary),
    ok("browser_status_review_html_exists", await exists(report.review_html_path), report.review_html_path),
    ok("browser_status_human_review_csv_exists", await exists(report.human_review_csv_path), report.human_review_csv_path),
    ok("browser_status_screenshots_dir_exists", await exists(report.screenshots_dir), report.screenshots_dir),
  ];

  let robotsBrowsed = 0;
  let missingEvidence = 0;
  let missingHumanReviewReason = 0;
  for (const result of report.results || []) {
    if (result.previous_source_status === "robots_disallowed" && result.skipped_browser !== true) robotsBrowsed += 1;
    if (!result.browser_status_evidence) missingEvidence += 1;
    if (result.browser_status === "human_review" && !result.human_review_reason) missingHumanReviewReason += 1;
  }
  checks.push(ok("browser_status_does_not_browse_robots_disallowed", robotsBrowsed === 0, { robotsBrowsed }));
  checks.push(ok("browser_status_results_have_evidence", missingEvidence === 0, { missingEvidence }));
  checks.push(ok("browser_status_human_review_has_reason", missingHumanReviewReason === 0, { missingHumanReviewReason }));
  return checks;
}

async function verifyMeasurementEstimate(report) {
  return [
    ...verifyTarget(report),
    ok("measurement_estimate_mode_is_report_only", report.mode === "estimate-only-no-llm", report.mode),
    ok("measurement_estimate_sent_zero_llm_rows", report.llm_rows_sent === 0, report.llm_rows_sent),
    ok("measurement_estimate_requires_approval", report.approval_required_before_llm_run === true, report.approval_required_before_llm_run),
    ok("measurement_estimate_has_strata", Array.isArray(report.source_site_strata), report.source_site_strata?.length),
    ok("measurement_estimate_has_sample_summary", Boolean(report.sample_summary), report.sample_summary),
    ok("measurement_estimate_has_cost_estimate", Boolean(report.cost_estimate), report.cost_estimate),
    ok("measurement_estimate_has_token_estimates", Number(report.cost_estimate?.estimated_input_tokens) > 0 && Number(report.cost_estimate?.estimated_output_tokens) > 0, report.cost_estimate),
  ];
}

async function verifyAttributes(report) {
  const checks = [
    ...verifyTarget(report),
    ok("attributes_has_pregnancy_parser_version", Boolean(report.pregnancy_parser_version), report.pregnancy_parser_version),
    ok("attributes_has_full_body_reset_version", Boolean(report.full_body_reset_version), report.full_body_reset_version),
    ok("attributes_is_dry_run_or_apply", ["dry-run", "apply"].includes(report.mode), report.mode),
    ok("attributes_has_before_counts", Boolean(report.before_counts), report.before_counts),
    ok("attributes_has_reset_policy", Boolean(report.full_body_visible_reset_policy), report.full_body_visible_reset_policy),
    ok("attributes_has_reset_sample", Array.isArray(report.full_body_reset_sample), report.full_body_reset_sample?.length),
    ok("attributes_reports_pregnancy_scan_count", Number.isFinite(Number(report.pregnancy_candidate_rows_scanned)), report.pregnancy_candidate_rows_scanned),
  ];

  let missingPregnancyEvidence = 0;
  for (const update of report.sample_weeks_pregnant_updates || []) {
    if (!update.pregnancy_evidence) missingPregnancyEvidence += 1;
  }
  checks.push(ok("attributes_pregnancy_updates_have_evidence", missingPregnancyEvidence === 0, { missingPregnancyEvidence }));
  if (report.mode === "apply") {
    checks.push(ok("attributes_apply_has_after_counts", Boolean(report.after_counts), report.after_counts));
    checks.push(ok("attributes_apply_left_no_full_body_true", Number(report.after_counts?.full_body_true || 0) === 0, report.after_counts));
  }
  return checks;
}

async function verifyCrops(report) {
  const writable = new Set(["whole_body", "garment_priority", "garment_partial"]);
  const planned = Array.isArray(report.planned_writes) ? report.planned_writes : [];
  let badMode = 0;
  let badWindow = 0;
  let badSpec = 0;
  for (const w of planned) {
    if (!writable.has(w.mode)) badMode += 1;
    const c = w.crop_spec || {};
    if (c.mode !== "cover-window" || c.source !== "auto") badSpec += 1;
    for (const k of ["windowXPct", "windowYPct", "windowWPct", "windowHPct"]) {
      const v = Number(c[k]);
      if (!Number.isFinite(v) || v < 0 || v > 100) badWindow += 1;
    }
  }
  return [
    ...verifyTarget(report),
    ok("crops_is_dry_run_or_apply", ["dry-run", "apply"].includes(report.mode), report.mode),
    ok("crops_has_model_version", Boolean(report.crop_model_version), report.crop_model_version),
    ok("crops_has_planned_writes", planned.length > 0, planned.length),
    ok("crops_only_writable_modes", badMode === 0, { badMode, rule: report.skip_rule }),
    ok("crops_specs_are_cover_window_auto", badSpec === 0, { badSpec }),
    ok("crops_window_pcts_in_range", badWindow === 0, { badWindow }),
    ok("crops_head_priority_skipped", !(report.skips && report.skips.mode_head_priority > 0 && badMode > 0), report.skips),
  ];
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Dev refresh report verifier guard" });

  if (!reportPath) throw new Error("Usage: npm run dev-images:report:verify -- --type=<taxonomy|orientation|status|browser-status|measurement-estimate|attributes> --report=/absolute/path/report.json");
  const resolvedReportPath = path.resolve(reportPath);
  const report = JSON.parse(await readFile(resolvedReportPath, "utf8"));
  const inferredType =
    reportType ||
    (report.extractor_version ? "taxonomy" : report.orientation_model_version ? "orientation" : report.browser_checker_version ? "browser-status" : report.checker_version ? "status" : report.estimator_version ? "measurement-estimate" : report.full_body_reset_version ? "attributes" : report.crop_model_version ? "crops" : null);
  if (!inferredType) throw new Error("Could not infer report type. Pass --type=taxonomy, --type=orientation, --type=status, --type=browser-status, --type=measurement-estimate, --type=attributes, or --type=crops.");

  let checks;
  if (inferredType === "taxonomy") checks = await verifyTaxonomy(report);
  else if (inferredType === "orientation") checks = await verifyOrientation(report);
  else if (inferredType === "status") checks = await verifyStatus(report);
  else if (inferredType === "browser-status") checks = await verifyBrowserStatus(report);
  else if (inferredType === "measurement-estimate") checks = await verifyMeasurementEstimate(report);
  else if (inferredType === "attributes") checks = await verifyAttributes(report);
  else if (inferredType === "crops") checks = await verifyCrops(report);
  else throw new Error(`Unsupported report type: ${inferredType}`);

  const passed = checks.every((check) => check.ok);
  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const verifierReportPath = path.join(
    reportsDir,
    `dev_refresh_report_verify_${inferredType}_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`,
  );
  await writeFile(
    verifierReportPath,
    JSON.stringify(
      {
        generated_at: generatedAt,
        supabase_url: guard.supabaseUrl,
        supabase_project_ref: guard.projectRef,
        report_path: resolvedReportPath,
        report_type: inferredType,
        passed,
        checks,
      },
      null,
      2,
    ) + "\n",
    "utf8",
  );
  console.log(`Wrote dev refresh report verification: ${verifierReportPath}`);
  console.log(`Report type: ${inferredType}`);
  console.log(`Checks passed: ${checks.filter((check) => check.ok).length}/${checks.length}`);
  console.log(`Passed: ${passed}`);
  if (!passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
