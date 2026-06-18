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
const taxonomyReportPath = parseArg("taxonomy-report");
const verifiedReportPath = parseArg("verified-report");
const approvalReportPath = parseArg("approval-report");
const allowedConfidence = new Set(
  String(parseArg("allowed-confidence", "high,medium"))
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);
const blockedSourceFields = new Set(["workbook_fallback"]);
const blockedExtractorVersions = new Set([
  "product_page_taxonomy_rules_v3_jumpsuits_primary_repair",
]);

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function timestampStem(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(".", "");
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlTextArray(values) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  return `array[${items.map(sqlString).join(",")}]::text[]`;
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

async function requireTaxonomyReport() {
  if (!taxonomyReportPath) {
    throw new Error(
      "Usage: npm run dev-images:taxonomy:promote -- --taxonomy-report=/absolute/path/report.json --verified-report=/absolute/path/verify.json [--apply]",
    );
  }
  const resolved = path.resolve(taxonomyReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.mode !== "dry-run" || !report.extractor_version) {
    throw new Error(`Taxonomy report is not a taxonomy dry-run report: ${resolved}`);
  }
  if (blockedExtractorVersions.has(report.extractor_version)) {
    throw new Error(
      `Taxonomy report uses blocked extractor version ${report.extractor_version}: ${resolved}`,
    );
  }
  return { resolved, report };
}

async function requirePassedVerificationReport(expectedTaxonomyReportPath) {
  if (!verifiedReportPath) {
    throw new Error("Promotion requires --verified-report=/absolute/path/dev_refresh_report_verify_taxonomy_*.json.");
  }
  const resolved = path.resolve(verifiedReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.report_type !== "taxonomy" || report.passed !== true) {
    throw new Error(`Verification report did not pass for taxonomy: ${resolved}`);
  }
  if (path.resolve(report.report_path) !== path.resolve(expectedTaxonomyReportPath)) {
    throw new Error(
      `Verification report points to ${report.report_path}, not taxonomy report ${expectedTaxonomyReportPath}.`,
    );
  }
  return { resolved, report };
}

async function requireApprovalReport(expectedTaxonomyReportPath, plannedRows) {
  if (!approvalReportPath) {
    if (apply) {
      throw new Error(
        "Taxonomy apply requires --approval-report=/absolute/path/taxonomy-review-decisions/dev_taxonomy_review_decisions_*.json from the taxonomy review dashboard.",
      );
    }
    return { resolved: null, approvedIds: null, report: null };
  }
  const resolved = path.resolve(approvalReportPath);
  const report = JSON.parse(await readFile(resolved, "utf8"));
  if (report.review_dashboard_version !== "taxonomy_review_dashboard_v1") {
    throw new Error(`Approval report is not a taxonomy review dashboard report: ${resolved}`);
  }
  const expectedResolved = path.resolve(expectedTaxonomyReportPath);
  const reportTaxonomyPath = report.taxonomy_report_path && report.taxonomy_report_path !== "multiple taxonomy audit reports"
    ? path.resolve(report.taxonomy_report_path)
    : null;
  const reportTaxonomyPaths = Array.isArray(report.taxonomy_report_paths)
    ? report.taxonomy_report_paths.map((reportPath) => path.resolve(reportPath))
    : [];
  const approvalCoversExpectedReport = reportTaxonomyPath === expectedResolved || reportTaxonomyPaths.includes(expectedResolved);
  if (!approvalCoversExpectedReport) {
    throw new Error(
      `Approval report points to ${report.taxonomy_report_path}, not taxonomy report ${expectedTaxonomyReportPath}.`,
    );
  }
  const shouldScopeDecisions = Array.isArray(report.decisions) && reportTaxonomyPaths.length;
  const scopedDecisions = shouldScopeDecisions
    ? report.decisions.filter((decision) => decision.taxonomy_report_path && path.resolve(decision.taxonomy_report_path) === expectedResolved)
    : Array.isArray(report.decisions)
      ? report.decisions
      : [];
  const approvedIds = new Set(
    shouldScopeDecisions || scopedDecisions.length
      ? scopedDecisions.filter((decision) => decision.decision === "approved").map((decision) => decision.product_page_id)
      : report.approved_product_page_ids || [],
  );
  const plannedIds = new Set(plannedRows.map((row) => row.product_page_id));
  const unknownApproved = Array.from(approvedIds).filter((id) => !plannedIds.has(id));
  if (unknownApproved.length) {
    throw new Error(`Approval report contains product_page_ids not present in planned taxonomy updates: ${unknownApproved.slice(0, 5).join(", ")}`);
  }
  const scopedReport = shouldScopeDecisions
    ? {
        ...report,
        decision_count: scopedDecisions.length,
        approved_count: approvedIds.size,
        rejected_count: scopedDecisions.filter((decision) => decision.decision === "rejected").length,
        not_product_count: scopedDecisions.filter((decision) => decision.decision === "not_product").length,
        needs_review_count: scopedDecisions.filter((decision) => decision.decision === "needs_review").length,
      }
    : report;
  return { resolved, approvedIds, report: scopedReport };
}

function tagAllowed(tag) {
  return tag?.evidence && tag?.source_field && !blockedSourceFields.has(tag.source_field);
}

function categoryAllowed(result) {
  const primary = result.proposed?.primaryCategory || null;
  return Boolean(
    primary &&
      !result.proposed?.categoryAmbiguous &&
      allowedConfidence.has(primary.category_confidence) &&
      !blockedSourceFields.has(primary.category_source_field),
  );
}

function urlFallbackAllowed(result) {
  if (result.skip_reason !== "robots_url_fallback") return true;
  return result.url_fallback_guard?.passed === true;
}

function plannedPromotions(taxonomyReport) {
  const rows = [];
  for (const result of taxonomyReport.results || []) {
    if (!urlFallbackAllowed(result)) continue;
    if (result.proposed?.categoryAmbiguous) continue;
    const primary = result.proposed?.primaryCategory || null;
    const hasAllowedCategory = categoryAllowed(result);
    const itemTags = (result.proposed?.itemTags || []).filter(tagAllowed);
    const attributeTags = (result.proposed?.attributeTags || []).filter(tagAllowed);

    if (!hasAllowedCategory) continue;
    if (!itemTags.length && !attributeTags.length && !primary) continue;
    rows.push({
      product_page_id: result.product_page_id,
      normalized_product_page_url: result.normalized_product_page_url,
      final_url: result.final_url || null,
      category: primary,
      catalog: result.catalog || null,
      item_tags: itemTags,
      attribute_tags: attributeTags,
      extractor_version: taxonomyReport.extractor_version,
    });
  }
  return rows;
}

function skipReason(result) {
  if (result.skipped) return "audit_skipped";
  if (!urlFallbackAllowed(result)) return "url_fallback_hallucination_guard";
  if (result.proposed?.categoryAmbiguous) return "ambiguous_category";
  if (!categoryAllowed(result)) return "missing_primary_category";
  return "no_allowed_taxonomy_updates";
}

function skipDescription(result) {
  if (result.skip_description) return result.skip_description;
  if (result.skipped) {
    if (String(result.skip_reason || "").startsWith("http_status_")) {
      return `Fetched URL returned ${result.http_status || result.skip_reason}; likely unavailable or not a usable product page.`;
    }
    if (result.skip_reason === "redirected_to_homepage") return "Product URL redirected to the site homepage instead of a product page.";
    if (result.skip_reason === "timeout") return "Fetch timed out before usable product-page content could be read.";
    if (result.skip_reason === "fetch_error") return `Fetch failed: ${result.error || "unknown error"}.`;
    if (result.skip_reason === "robots_disallowed") return "Robots.txt disallowed fetching this URL.";
    if (result.skip_reason === "invalid_url") return "Product page URL is invalid.";
    if (String(result.skip_reason || "").startsWith("non_html:")) return "Fetched URL did not return HTML product-page content.";
    return `Audit skipped this URL: ${result.skip_reason || "unknown reason"}.`;
  }
  if (!urlFallbackAllowed(result)) {
    const reasons = result.url_fallback_guard?.reasons || [];
    return `Robots.txt blocked page fetch; URL-only fallback did not pass hallucination guard${reasons.length ? ` (${reasons.join("; ")})` : ""}.`;
  }
  if (result.skip_reason === "robots_url_fallback") {
    const reasons = result.url_fallback_guard?.reasons || [];
    return `Robots.txt blocked page fetch; URL-only fallback found no safe taxonomy evidence${reasons.length ? ` (${reasons.join("; ")})` : ""}.`;
  }
  if (result.proposed?.categoryAmbiguous) return "Taxonomy evidence produced ambiguous primary categories, so no update was planned.";
  if (!categoryAllowed(result)) return "No allowed primary category was available, so this product page cannot be human-approved for taxonomy promotion.";
  return "No allowed taxonomy category or tags had enough safe evidence to plan an update.";
}

function skippedRows(taxonomyReport, planned) {
  const plannedIds = new Set(planned.map((row) => row.product_page_id));
  return (taxonomyReport.results || [])
    .filter((result) => !plannedIds.has(result.product_page_id))
    .map((result) => ({
      product_page_id: result.product_page_id,
      normalized_product_page_url: result.normalized_product_page_url,
      final_url: result.final_url || null,
      http_status: result.http_status || null,
      robots_disallowed: result.robots_disallowed ?? null,
      robots_rule: result.robots_rule || null,
      skipped_in_audit: Boolean(result.skipped),
      audit_skip_reason: result.skip_reason || null,
      audit_error: result.error || null,
      category_ambiguous: Boolean(result.proposed?.categoryAmbiguous),
      proposed_primary_category: result.proposed?.primaryCategory?.mother_category_id || null,
      url_fallback_guard_passed: result.url_fallback_guard?.passed ?? null,
      url_fallback_guard_reasons: (result.url_fallback_guard?.reasons || []).join("; "),
      skip_reason: skipReason(result),
      skip_description: skipDescription(result),
    }));
}

function updateSql(rows, taxonomyReportPathForMetadata) {
  const statements = [];
  for (const row of rows) {
    const catalog = row.catalog || {};
    if (row.category) {
      statements.push(`
update staging.product_pages
set
  mother_category_id = ${sqlString(row.category.mother_category_id)},
  category_confidence = ${sqlString(row.category.category_confidence)},
  category_evidence = ${sqlString(row.category.category_evidence)},
  category_source_field = ${sqlString(row.category.category_source_field)},
  category_extractor_version = ${sqlString(row.extractor_version)},
  category_checked_at = now(),
  catalog_image_url = coalesce(nullif(${sqlString(catalog.catalog_image_url)}, ''), catalog_image_url),
  catalog_image_urls = case
    when cardinality(${sqlTextArray(catalog.catalog_image_urls)}) > 0 then ${sqlTextArray(catalog.catalog_image_urls)}
    else catalog_image_urls
  end,
  catalog_image_source = coalesce(nullif(${sqlString(catalog.catalog_image_source)}, ''), catalog_image_source),
  catalog_image_fetched_at = case when ${sqlString(catalog.catalog_image_fetch_status || "")} = '' then catalog_image_fetched_at else now() end,
  catalog_image_fetch_status = coalesce(nullif(${sqlString(catalog.catalog_image_fetch_status || "")}, ''), catalog_image_fetch_status),
  catalog_image_fetch_error = nullif(${sqlString(catalog.catalog_image_fetch_error || "")}, ''),
  needs_manual_review = false,
  raw_metadata = raw_metadata || ${sqlJson({
    taxonomy_promoted_at: new Date().toISOString(),
    taxonomy_report_path: taxonomyReportPathForMetadata,
    taxonomy_final_url: row.final_url,
    taxonomy_manually_reviewed_at: new Date().toISOString(),
    taxonomy_manual_review_source: "taxonomy_review_dashboard",
  })}
where id = ${sqlString(row.product_page_id)}::uuid;`);
    } else {
      statements.push(`
update staging.product_pages
set
  category_extractor_version = ${sqlString(row.extractor_version)},
  category_checked_at = now(),
  catalog_image_url = coalesce(nullif(${sqlString(catalog.catalog_image_url)}, ''), catalog_image_url),
  catalog_image_urls = case
    when cardinality(${sqlTextArray(catalog.catalog_image_urls)}) > 0 then ${sqlTextArray(catalog.catalog_image_urls)}
    else catalog_image_urls
  end,
  catalog_image_source = coalesce(nullif(${sqlString(catalog.catalog_image_source)}, ''), catalog_image_source),
  catalog_image_fetched_at = case when ${sqlString(catalog.catalog_image_fetch_status || "")} = '' then catalog_image_fetched_at else now() end,
  catalog_image_fetch_status = coalesce(nullif(${sqlString(catalog.catalog_image_fetch_status || "")}, ''), catalog_image_fetch_status),
  catalog_image_fetch_error = nullif(${sqlString(catalog.catalog_image_fetch_error || "")}, ''),
  needs_manual_review = false,
  raw_metadata = raw_metadata || ${sqlJson({
    taxonomy_promoted_at: new Date().toISOString(),
    taxonomy_report_path: taxonomyReportPathForMetadata,
    taxonomy_final_url: row.final_url,
    taxonomy_category_update_skipped: true,
    taxonomy_manually_reviewed_at: new Date().toISOString(),
    taxonomy_manual_review_source: "taxonomy_review_dashboard",
  })}
where id = ${sqlString(row.product_page_id)}::uuid;`);
    }

    for (const tag of row.item_tags || []) {
      statements.push(`
insert into staging.product_page_clothing_type_tags (product_page_id, clothing_type_id, evidence)
values (${sqlString(row.product_page_id)}::uuid, ${sqlString(tag.clothing_type_id)}, ${sqlString(tag.evidence)})
on conflict (product_page_id, clothing_type_id) do update set
  evidence = excluded.evidence;`);
    }
    for (const tag of row.attribute_tags || []) {
      statements.push(`
insert into staging.product_page_attribute_tags
  (product_page_id, tag_type, tag_id, label, confidence, evidence, source_field, extractor_version)
values
  (${sqlString(row.product_page_id)}::uuid, ${sqlString(tag.tag_type)}, ${sqlString(tag.tag_id)}, ${sqlString(tag.label)}, ${sqlString(tag.confidence)}, ${sqlString(tag.evidence)}, ${sqlString(tag.source_field)}, ${sqlString(row.extractor_version)})
on conflict (product_page_id, tag_type, tag_id) do update set
  label = excluded.label,
  confidence = excluded.confidence,
  evidence = excluded.evidence,
  source_field = excluded.source_field,
  extractor_version = excluded.extractor_version,
  updated_at = now();`);
    }
  }
  return `begin;\n${statements.join("\n")}\ncommit;`;
}

function summarize(rows, skipped) {
  const categories = {};
  let itemTagCount = 0;
  let attributeTagCount = 0;
  for (const row of rows) {
    const category = row.category?.mother_category_id || "category_not_updated";
    categories[category] = (categories[category] || 0) + 1;
    itemTagCount += row.item_tags.length;
    attributeTagCount += row.attribute_tags.length;
  }
  const skippedByReason = {};
  for (const row of skipped) skippedByReason[row.skip_reason] = (skippedByReason[row.skip_reason] || 0) + 1;
  return { categories, item_tag_count: itemTagCount, attribute_tag_count: attributeTagCount, skipped_by_reason: skippedByReason };
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function buildSkippedRowsCsv(rows) {
  const headers = [
    "product_page_id",
    "normalized_product_page_url",
    "final_url",
    "http_status",
    "robots_disallowed",
    "robots_rule",
    "skip_reason",
    "skip_description",
    "audit_skip_reason",
    "audit_error",
    "category_ambiguous",
    "proposed_primary_category",
    "url_fallback_guard_passed",
    "url_fallback_guard_reasons",
  ];
  return [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n") + "\n";
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Taxonomy promotion guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const { resolved: resolvedTaxonomyReportPath, report: taxonomyReport } = await requireTaxonomyReport();
  const { resolved: resolvedVerifiedReportPath } = await requirePassedVerificationReport(resolvedTaxonomyReportPath);
  const planned = plannedPromotions(taxonomyReport);
  const { resolved: resolvedApprovalReportPath, approvedIds, report: approvalReport } = await requireApprovalReport(resolvedTaxonomyReportPath, planned);
  const approvedPlanned = approvedIds ? planned.filter((row) => approvedIds.has(row.product_page_id)) : planned;
  const skipped = skippedRows(taxonomyReport, planned);
  if (approvedIds) {
    for (const row of planned) {
      if (!approvedIds.has(row.product_page_id)) {
        skipped.push({
          product_page_id: row.product_page_id,
          normalized_product_page_url: row.normalized_product_page_url,
          skipped_in_audit: false,
          audit_skip_reason: null,
      category_ambiguous: false,
      proposed_primary_category: row.category?.mother_category_id || null,
      skip_reason: row.category ? "not_human_approved" : "missing_primary_category",
      skip_description: row.category
        ? "Planned taxonomy update was not included in the human approval report."
        : "No primary category was available, so this product page was not eligible for human approval.",
    });
  }
    }
  }

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportStem = `dev_taxonomy_promotion_${timestampStem(new Date(generatedAt))}`;
  const reportPath = path.join(reportsDir, `${reportStem}.json`);
  const skippedRowsCsvPath = path.join(reportsDir, `${reportStem}_skipped_rows.csv`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    taxonomy_report_path: resolvedTaxonomyReportPath,
    verified_report_path: resolvedVerifiedReportPath,
    approval_report_path: resolvedApprovalReportPath,
    approval_summary: approvalReport ? {
      decision_count: approvalReport.decision_count,
      approved_count: approvalReport.approved_count,
      rejected_count: approvalReport.rejected_count,
      needs_review_count: approvalReport.needs_review_count,
    } : null,
    allowed_confidence: Array.from(allowedConfidence),
    blocked_source_fields: Array.from(blockedSourceFields),
    planned_update_count: approvedPlanned.length,
    skipped_count: skipped.length,
    skipped_rows_csv_path: skippedRowsCsvPath,
    summary: summarize(approvedPlanned, skipped),
    planned_updates: approvedPlanned,
    skipped_rows: skipped,
  };

  if (apply) {
    requireExplicitWriteFlag();
    if (approvedPlanned.length) runPsql(process.env.DEV_DATABASE_URL, updateSql(approvedPlanned, resolvedTaxonomyReportPath));
  }

  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(skippedRowsCsvPath, buildSkippedRowsCsv(skipped), "utf8");
  console.log(`Wrote taxonomy promotion report: ${reportPath}`);
  console.log(`Wrote taxonomy promotion skipped-rows CSV: ${skippedRowsCsvPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Planned updates: ${approvedPlanned.length}`);
  console.log(`Skipped rows: ${skipped.length}`);
  console.log(`Summary: ${JSON.stringify(report.summary)}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
