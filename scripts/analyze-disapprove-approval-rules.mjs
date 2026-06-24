import ExcelJS from "exceljs";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "..");
const dataRoot = path.resolve(repoRoot, "../FWM_Data");
const packageDir = path.join(
  dataRoot,
  "03_cv_annotated_pending_human_review/partial_170000_rows_cv_gated",
);
const returnsDir = path.join(
  dataRoot,
  "04_human_reviewed_ready_to_publish/human_labeled_returns",
);
const manifestPath = path.join(returnsDir, "human_labeled_returns_manifest.json");
const reportStamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
const reportDir = path.join(dataRoot, "_reports", `disapprove_approval_cv_experiment_${reportStamp}`);

const numericFeatures = [
  "person_count_yolo_detect",
  "main_person_height_pct_yolo_detect",
  "main_person_bbox_area_pct_yolo_detect",
  "body_coverage_score_yolo_pose",
];

const displayFields = [
  "source_family",
  "source_site_display",
  "review_row_key",
  "image_url_to_use",
  "raw_scraped_image_url",
  "product_page_url_display",
  "brand",
  "product_title_raw",
  "product_category_raw",
  "product_variant_raw",
  "clothing_type_id",
  "size_display",
  "height_in_display",
  "weight_lbs_display",
  "waist_in",
  "hips_in_display",
  "bust_in_display",
  "bra_band_in_display",
  "cupsize_display",
  "inseam_inches_display",
  "user_comment",
  "cv_decision",
  "cv_reason_code",
  "cv_reason_summary",
  "sorter_recommendation",
  "sorter_reason_codes",
  ...numericFeatures,
];

function asText(value) {
  if (value == null) return "";
  if (typeof value === "object" && "text" in value) return String(value.text ?? "");
  if (typeof value === "object" && "result" in value) return String(value.result ?? "");
  return String(value);
}

function asNumber(value) {
  const text = asText(value).trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function getRowKey(raw, rowNumber) {
  return raw.review_row_key || `${raw.source_file || "unknown"}::${raw.source_row_number || rowNumber}`;
}

function quantile(values, q) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * q;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

function summarizeNumeric(values) {
  const clean = values.filter((value) => Number.isFinite(value));
  return {
    count: clean.length,
    mean: clean.length ? clean.reduce((sum, value) => sum + value, 0) / clean.length : null,
    p10: quantile(clean, 0.1),
    p25: quantile(clean, 0.25),
    median: quantile(clean, 0.5),
    p75: quantile(clean, 0.75),
    p90: quantile(clean, 0.9),
  };
}

function round(value, digits = 4) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

function rate(numerator, denominator) {
  return denominator ? numerator / denominator : 0;
}

function evaluateCondition(rows, condition) {
  let support = 0;
  let approvals = 0;
  for (const row of rows) {
    if (!condition.test(row)) continue;
    support += 1;
    if (row.label === "APPROVE") approvals += 1;
  }
  return { support, approvals, rejects: support - approvals };
}

function addCondition(candidates, rows, baselineRate, condition) {
  const result = evaluateCondition(rows, condition);
  if (result.support < 20 || result.approvals < 5) return;
  const precision = rate(result.approvals, result.support);
  const recall = rate(result.approvals, rows.filter((row) => row.label === "APPROVE").length);
  candidates.push({
    name: condition.name,
    support: result.support,
    approvals: result.approvals,
    rejects: result.rejects,
    precision,
    recall,
    lift: baselineRate ? precision / baselineRate : 0,
  });
}

function csvEscape(value) {
  const text = value == null ? "" : String(value);
  if (!/[",\n]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

function toCsv(rows, columns) {
  return [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => csvEscape(row[column])).join(",")),
  ].join("\n") + "\n";
}

async function readWorkbookRows(filename, wantedKeys) {
  const workbookPath = path.join(packageDir, filename);
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(workbookPath);
  const worksheet = workbook.worksheets[0];
  const headers = [];
  worksheet.getRow(1).eachCell({ includeEmpty: true }, (cell, colNumber) => {
    headers[colNumber] = asText(cell.value).trim();
  });

  const rowsByKey = new Map();
  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber === 1) return;
    const raw = {};
    for (let colNumber = 1; colNumber < headers.length; colNumber += 1) {
      const header = headers[colNumber];
      if (!header) continue;
      raw[header] = asText(row.getCell(colNumber).value);
    }
    const key = getRowKey(raw, rowNumber);
    if (wantedKeys.has(key)) rowsByKey.set(key, raw);
  });
  return rowsByKey;
}

async function readReturnWorkbookRows(filename) {
  const workbookPath = path.join(returnsDir, filename);
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(workbookPath);
  const worksheet = workbook.worksheets[0];
  const headers = [];
  worksheet.getRow(1).eachCell({ includeEmpty: true }, (cell, colNumber) => {
    headers[colNumber] = asText(cell.value).trim();
  });

  const rows = [];
  const exportStamp = filename.match(/_(\d{8}T\d{6}Z)\.xlsx$/)?.[1] || "";
  const partFile = filename.replace(/^human_labeled_/, "supabase_image_review_").replace(/_\d{8}T\d{6}Z\.xlsx$/, ".xlsx");
  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber === 1) return;
    const raw = {};
    for (let colNumber = 1; colNumber < headers.length; colNumber += 1) {
      const header = headers[colNumber];
      if (!header) continue;
      raw[header] = asText(row.getCell(colNumber).value);
    }
    const reviewRowKey = getRowKey(raw, rowNumber);
    rows.push({
      ...raw,
      part_file: partFile,
      review_row_key: reviewRowKey,
      export_stamp: exportStamp,
      return_workbook: filename,
    });
  });
  return rows;
}

function formatPercent(value, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function formatNumber(value, digits = 3) {
  return Number.isFinite(value) ? value.toFixed(digits) : "";
}

function topRowsByCount(map, limit = 20) {
  return [...map.values()].sort((a, b) => b.total - a.total || b.approvals - a.approvals).slice(0, limit);
}

function bumpGroup(map, key, label) {
  const safeKey = key || "(blank)";
  const entry = map.get(safeKey) || { value: safeKey, total: 0, approvals: 0, rejects: 0 };
  entry.total += 1;
  if (label === "APPROVE") entry.approvals += 1;
  else entry.rejects += 1;
  map.set(safeKey, entry);
}

function addRates(entries, baselineRate) {
  return entries.map((entry) => ({
    ...entry,
    approval_rate: rate(entry.approvals, entry.total),
    lift: baselineRate ? rate(entry.approvals, entry.total) / baselineRate : 0,
  }));
}

async function main() {
  await mkdir(reportDir, { recursive: true });
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const manifestDecisions = Object.values(manifest.decisions || {}).filter(
    (decision) => decision.bucket === "disapprove_candidates",
  );

  const returnFiles = (await readdir(returnsDir))
    .filter((filename) => /^human_labeled_disapprove_candidates_part_\d{3}_\d{8}T\d{6}Z\.xlsx$/.test(filename))
    .sort();
  const latestByKey = new Map();
  for (const filename of returnFiles) {
    console.log(`Reading return workbook ${filename}`);
    for (const row of await readReturnWorkbookRows(filename)) {
      const prior = latestByKey.get(row.review_row_key);
      if (!prior || String(row.export_stamp).localeCompare(String(prior.export_stamp)) >= 0) {
        latestByKey.set(row.review_row_key, row);
      }
    }
  }

  let rows = [...latestByKey.values()].map((raw) => {
    const label = raw.production_decision === "APPROVE" ? "APPROVE" : "DISAPPROVE";
    const row = {
      label,
      human_state: raw.production_decision,
      part_file: raw.part_file,
      review_row_key: raw.review_row_key,
      reviewed_at: "",
      export_stamp: raw.export_stamp,
      rejection_reason: raw.rejection_reason,
      review_notes: raw.review_notes,
      return_workbook: raw.return_workbook,
    };
    for (const field of displayFields) row[field] = raw[field] || "";
    for (const field of numericFeatures) row[field] = asNumber(raw[field]);
    return row;
  });

  if (rows.length === 0) {
    const keysByPart = new Map();
    for (const decision of manifestDecisions) {
    const partFile = decision.part_file;
    const key = decision.review_row_key;
    if (!partFile || !key) continue;
    if (!keysByPart.has(partFile)) keysByPart.set(partFile, new Set());
    keysByPart.get(partFile).add(key);
    }

    const workbookRowsByPart = new Map();
    for (const [partFile, wantedKeys] of [...keysByPart.entries()].sort()) {
    console.log(`Reading ${partFile} (${wantedKeys.size} saved decisions)`);
    workbookRowsByPart.set(partFile, await readWorkbookRows(partFile, wantedKeys));
    }

    rows = [];
    for (const decision of manifestDecisions) {
    const raw = workbookRowsByPart.get(decision.part_file)?.get(decision.review_row_key) || {};
    const label = decision.human_state === "APPROVE" ? "APPROVE" : "DISAPPROVE";
    const row = {
      label,
      human_state: decision.human_state,
      part_file: decision.part_file,
      review_row_key: decision.review_row_key,
      reviewed_at: decision.reviewed_at,
      export_stamp: decision.export_stamp,
      rejection_reason: decision.rejection_reason,
      review_notes: decision.review_notes,
    };
    for (const field of displayFields) row[field] = raw[field] || decision[field] || "";
    for (const field of numericFeatures) row[field] = asNumber(raw[field]);
    rows.push(row);
    }
  }

  const approvals = rows.filter((row) => row.label === "APPROVE");
  const rejects = rows.filter((row) => row.label !== "APPROVE");
  const baselineRate = rate(approvals.length, rows.length);

  const groups = {
    cv_reason_code: new Map(),
    sorter_reason_codes: new Map(),
    clothing_type_id: new Map(),
    source_family: new Map(),
    has_face_yunet: new Map(),
  };
  for (const row of rows) {
    for (const groupName of Object.keys(groups)) bumpGroup(groups[groupName], row[groupName], row.label);
  }

  const groupedSummaries = Object.fromEntries(
    Object.entries(groups).map(([name, map]) => [name, addRates(topRowsByCount(map, 40), baselineRate)]),
  );

  const numericSummary = Object.fromEntries(
    numericFeatures.map((feature) => [
      feature,
      {
        approve: summarizeNumeric(approvals.map((row) => row[feature])),
        disapprove: summarizeNumeric(rejects.map((row) => row[feature])),
      },
    ]),
  );

  const candidates = [];
  const uniqueValues = (field) => [...new Set(rows.map((row) => row[field]).filter(Boolean))];
  for (const field of ["cv_reason_code", "sorter_reason_codes", "clothing_type_id", "source_family", "has_face_yunet"]) {
    for (const value of uniqueValues(field)) {
      addCondition(candidates, rows, baselineRate, {
        name: `${field} == ${value}`,
        test: (row) => row[field] === value,
      });
    }
  }
  for (const feature of numericFeatures) {
    const values = rows.map((row) => row[feature]).filter((value) => Number.isFinite(value));
    const thresholds = [...new Set([0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1, ...[0.1, 0.25, 0.5, 0.75, 0.9].map((q) => round(quantile(values, q), 3))])]
      .filter((value) => value != null)
      .sort((a, b) => a - b);
    for (const threshold of thresholds) {
      addCondition(candidates, rows, baselineRate, {
        name: `${feature} >= ${threshold}`,
        test: (row) => Number.isFinite(row[feature]) && row[feature] >= threshold,
      });
      addCondition(candidates, rows, baselineRate, {
        name: `${feature} <= ${threshold}`,
        test: (row) => Number.isFinite(row[feature]) && row[feature] <= threshold,
      });
    }
  }

  const baseConditions = [
    ...uniqueValues("cv_reason_code").map((value) => ({
      name: `cv_reason_code == ${value}`,
      test: (row) => row.cv_reason_code === value,
    })),
    ...numericFeatures.flatMap((feature) => [0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 0.9].flatMap((threshold) => [
      {
        name: `${feature} >= ${threshold}`,
        test: (row) => Number.isFinite(row[feature]) && row[feature] >= threshold,
      },
      {
        name: `${feature} <= ${threshold}`,
        test: (row) => Number.isFinite(row[feature]) && row[feature] <= threshold,
      },
    ])),
  ];
  for (let i = 0; i < baseConditions.length; i += 1) {
    for (let j = i + 1; j < baseConditions.length; j += 1) {
      addCondition(candidates, rows, baselineRate, {
        name: `${baseConditions[i].name} AND ${baseConditions[j].name}`,
        test: (row) => baseConditions[i].test(row) && baseConditions[j].test(row),
      });
    }
  }

  const topRules = candidates
    .filter((candidate) => candidate.precision >= baselineRate * 1.25)
    .sort((a, b) => b.precision - a.precision || b.approvals - a.approvals)
    .slice(0, 50);
  const broadRules = candidates
    .filter((candidate) => candidate.approvals >= 50)
    .sort((a, b) => b.lift - a.lift || b.approvals - a.approvals)
    .slice(0, 50);

  const sampleApprovals = approvals
    .slice()
    .sort((a, b) => String(b.reviewed_at).localeCompare(String(a.reviewed_at)))
    .slice(0, 100);

  const summary = {
    generated_at: new Date().toISOString(),
    package_dir: packageDir,
    manifest_path: manifestPath,
    source_return_workbook_count: returnFiles.length,
    manifest_disapprove_candidate_decision_count: manifestDecisions.length,
    total_saved_disapprove_candidate_decisions: rows.length,
    approved_from_disapprove_candidates: approvals.length,
    kept_disapproved_from_disapprove_candidates: rejects.length,
    baseline_approval_rate: baselineRate,
    parts_analyzed: new Set(rows.map((row) => row.part_file)).size,
    numeric_summary: numericSummary,
    grouped_summaries: groupedSummaries,
    top_high_precision_rules: topRules,
    top_broad_lift_rules: broadRules,
  };

  await writeFile(path.join(reportDir, "summary.json"), JSON.stringify(summary, null, 2) + "\n", "utf8");
  await writeFile(
    path.join(reportDir, "rules.csv"),
    toCsv([...topRules, ...broadRules].map((rule) => ({
      ...rule,
      precision: round(rule.precision),
      recall: round(rule.recall),
      lift: round(rule.lift),
    })), ["name", "support", "approvals", "rejects", "precision", "recall", "lift"]),
    "utf8",
  );
  await writeFile(
    path.join(reportDir, "approved_disapprove_candidate_sample.csv"),
    toCsv(sampleApprovals, [
      "part_file",
      "review_row_key",
      "cv_reason_code",
      "sorter_reason_codes",
      "person_count_yolo_detect",
      "main_person_height_pct_yolo_detect",
      "main_person_bbox_area_pct_yolo_detect",
      "body_coverage_score_yolo_pose",
      "has_face_yunet",
      "clothing_type_id",
      "height_in_display",
      "weight_lbs_display",
      "size_display",
      "image_url_to_use",
      "product_page_url_display",
      "user_comment",
    ]),
    "utf8",
  );

  const lines = [];
  lines.push("# Disapprove Candidate Approval CV Experiment");
  lines.push("");
  lines.push(`Generated: ${summary.generated_at}`);
  lines.push(`Package: \`${packageDir}\``);
  lines.push(`Saved disapprove-candidate decisions analyzed: ${rows.length}`);
  lines.push(`Approved by human review: ${approvals.length} (${formatPercent(baselineRate)})`);
  lines.push(`Kept disapproved: ${rejects.length}`);
  lines.push("");
  lines.push("## Strongest Signals");
  lines.push("");
  for (const rule of broadRules.slice(0, 12)) {
    lines.push(
      `- ${rule.name}: ${rule.approvals}/${rule.support} approved (${formatPercent(rule.precision)}), lift ${rule.lift.toFixed(2)}, recall ${formatPercent(rule.recall)}.`,
    );
  }
  lines.push("");
  lines.push("## CV Reason Approval Rates");
  lines.push("");
  lines.push("| CV reason | total | approved | approval rate | lift |");
  lines.push("|---|---:|---:|---:|---:|");
  for (const entry of groupedSummaries.cv_reason_code) {
    lines.push(
      `| ${entry.value} | ${entry.total} | ${entry.approvals} | ${formatPercent(entry.approval_rate)} | ${entry.lift.toFixed(2)} |`,
    );
  }
  lines.push("");
  lines.push("## Numeric Feature Comparison");
  lines.push("");
  lines.push("| feature | approve median | disapprove median | approve p25-p75 | disapprove p25-p75 |");
  lines.push("|---|---:|---:|---:|---:|");
  for (const [feature, stats] of Object.entries(numericSummary)) {
    lines.push(
      `| ${feature} | ${formatNumber(stats.approve.median)} | ${formatNumber(stats.disapprove.median)} | ${formatNumber(stats.approve.p25)}-${formatNumber(stats.approve.p75)} | ${formatNumber(stats.disapprove.p25)}-${formatNumber(stats.disapprove.p75)} |`,
    );
  }
  lines.push("");
  lines.push("## Candidate Rules");
  lines.push("");
  lines.push("These are exploratory rules. Use them as triage or auto-review suggestions, not production writes, until validated on a held-out batch.");
  lines.push("");
  for (const rule of topRules.slice(0, 20)) {
    lines.push(
      `- ${rule.name}: precision ${formatPercent(rule.precision)}, support ${rule.support}, approvals ${rule.approvals}, lift ${rule.lift.toFixed(2)}.`,
    );
  }
  lines.push("");
  await writeFile(path.join(reportDir, "report.md"), lines.join("\n"), "utf8");

  console.log(JSON.stringify({
    reportDir,
    total: rows.length,
    approvals: approvals.length,
    baselineApprovalRate: round(baselineRate),
    topBroadRules: broadRules.slice(0, 5).map((rule) => ({
      name: rule.name,
      support: rule.support,
      approvals: rule.approvals,
      precision: round(rule.precision),
      lift: round(rule.lift),
    })),
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
