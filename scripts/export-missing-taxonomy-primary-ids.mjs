#!/usr/bin/env node

import { readdir, readFile, stat, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { assertApprovedDevSupabase, printGuardSummary } from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
const outputPathArg = parseArg("output");
const outputPath = outputPathArg
  ? path.resolve(outputPathArg)
  : path.join(reportsDir, `dev_taxonomy_missing_primary_ids_${timestampStem(new Date())}.txt`);
const summaryPath = outputPath.replace(/\.txt$/i, ".json");

function parseArg(name, defaultValue = "") {
  const prefix = `--${name}=`;
  const found = process.argv.find((arg) => arg.startsWith(prefix));
  return found ? found.slice(prefix.length) : defaultValue;
}

function timestampStem(date) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function primaryCategoryId(row) {
  return String(
    row?.proposed?.primaryCategory?.mother_category_id
      || row?.proposed?.primary_category?.mother_category_id
      || row?.proposed?.primaryCategory?.motherCategoryId
      || "",
  ).trim();
}

function rowProductPageId(row) {
  return String(row?.product_page_id || row?.productPageId || row?.product_page?.id || "").trim();
}

function rowReason(row) {
  return String(
    row?.skip_reason
      || row?.skipReason
      || row?.fallback_reason
      || row?.extraction_status
      || (row?.http_status ? `http_${row.http_status}` : "")
      || "<no reason field>",
  );
}

function rowDomain(row) {
  try {
    return new URL(row?.normalized_product_page_url || row?.final_url || "").hostname.replace(/^www\./i, "");
  } catch {
    return "<bad-url>";
  }
}

function bump(map, key) {
  map.set(key, (map.get(key) || 0) + 1);
}

function topEntries(map, limit = 25) {
  return Array.from(map.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([key, count]) => ({ key, count }));
}

async function readAuditReports() {
  const names = (await readdir(reportsDir))
    .filter((name) => /^dev_product_page_taxonomy_audit_.*\.json$/.test(name))
    .sort();
  const latestByProductPage = new Map();
  let allRows = 0;
  let allRowsWithPrimary = 0;

  for (const name of names) {
    const reportPath = path.join(reportsDir, name);
    const report = JSON.parse(await readFile(reportPath, "utf8"));
    const reportStat = await stat(reportPath);
    const generatedAt = report.generated_at || report.generatedAt || reportStat.mtime.toISOString();
    const results = Array.isArray(report.results) ? report.results : [];
    for (const row of results) {
      allRows += 1;
      if (primaryCategoryId(row)) allRowsWithPrimary += 1;
      const productPageId = rowProductPageId(row);
      if (!productPageId) continue;
      const previous = latestByProductPage.get(productPageId);
      if (!previous || String(generatedAt).localeCompare(String(previous.generatedAt)) >= 0) {
        latestByProductPage.set(productPageId, {
          report: name,
          generatedAt,
          row,
        });
      }
    }
  }

  return { names, latestByProductPage, allRows, allRowsWithPrimary };
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: false });
  printGuardSummary(guard, { prefix: "Missing taxonomy primary export guard" });

  const { names, latestByProductPage, allRows, allRowsWithPrimary } = await readAuditReports();
  const missing = [];
  const missingByReason = new Map();
  const missingByDomain = new Map();
  const missingSkippedSplit = new Map();
  const withPrimaryByCategory = new Map();

  for (const [productPageId, entry] of latestByProductPage.entries()) {
    const categoryId = primaryCategoryId(entry.row);
    if (categoryId) {
      bump(withPrimaryByCategory, categoryId);
      continue;
    }
    missing.push(productPageId);
    bump(missingByReason, rowReason(entry.row));
    bump(missingByDomain, rowDomain(entry.row));
    bump(missingSkippedSplit, entry.row?.skipped ? "skipped" : "not_skipped");
  }

  missing.sort();
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${missing.join("\n")}\n`);

  const summary = {
    generated_at: new Date().toISOString(),
    supabase_project_ref: guard.projectRef,
    audit_reports: names.length,
    latest_audit_report: names.at(-1) || null,
    all_collected_report_rows: allRows,
    all_rows_with_primary_category: allRowsWithPrimary,
    all_rows_missing_primary_category: allRows - allRowsWithPrimary,
    unique_latest_collected_product_pages: latestByProductPage.size,
    latest_with_primary_category: latestByProductPage.size - missing.length,
    latest_missing_primary_category: missing.length,
    latest_missing_skipped_split: Object.fromEntries(missingSkippedSplit),
    latest_missing_by_reason_or_status: topEntries(missingByReason, 50),
    latest_missing_by_domain: topEntries(missingByDomain, 50),
    latest_with_by_category: Object.fromEntries(
      Array.from(withPrimaryByCategory.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])),
    ),
    product_page_ids_path: outputPath,
  };
  await writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`);

  console.log(`Wrote missing primary taxonomy product-page IDs: ${outputPath}`);
  console.log(`Wrote missing primary taxonomy summary: ${summaryPath}`);
  console.log(`Latest missing primary category: ${summary.latest_missing_primary_category}`);
  console.log(`Latest with primary category: ${summary.latest_with_primary_category}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
