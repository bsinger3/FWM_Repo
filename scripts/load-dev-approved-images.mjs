#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import ExcelJS from "exceljs";
import {
  callSupabaseRest,
  assertApprovedDevSupabase,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import {
  defaultImageReviewPackageDir,
  defaultImageReviewReturnsDir,
  fwmDataDir,
} from "../tools/image-review-dashboard/paths.mjs";
import { parseWeeksPregnant } from "./lib/pregnancy-parser.mjs";
import { commentId } from "../tools/extraction-audit-dashboard/lib/analyze.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
// Optional corrected-measurement overrides (from the extraction audit), joined to
// each row by commentId(user_comment). When present, these replace the workbook's
// measurement columns so current-regex values land in dev images. See
// scripts/build-measurement-overrides.mjs.
const measurementOverridesPath = process.argv
  .find((arg) => arg.startsWith("--measurement-overrides="))
  ?.split("=")[1];
const measurementOverrides = measurementOverridesPath
  ? JSON.parse(await readFile(measurementOverridesPath, "utf8")).overrides
  : null;
let measurementOverrideHits = 0;
const resolveWorkbooks = process.argv.includes("--resolve-workbooks");
const sampleLimit = Number(process.argv.find((arg) => arg.startsWith("--sample-limit="))?.split("=")[1] || 20);
const fetchDevUrls = process.argv.includes("--fetch-dev-urls") || resolveWorkbooks;
const batchSize = Number(process.argv.find((arg) => arg.startsWith("--batch-size="))?.split("=")[1] || 250);
const skipDuplicateConflicts =
  process.env.FWM_DEV_IMAGE_LOAD_SKIP_DUPLICATE_CONFLICTS === "yes-reviewed-dry-run";

const CLOTHING_TYPE_ALIASES = new Map([
  ["bodysuits", "bodysuit"],
  ["bottom", "other"],
  ["capris", "pants"],
  ["clothing", "other"],
  ["coverup", "swimsuit"],
  ["jean", "jeans"],
  ["jegging", "leggings"],
  ["jeggings", "leggings"],
  ["one_piece", "swimsuit"],
  ["pant", "pants"],
  ["short", "shorts"],
  ["swimwear", "swimsuit"],
  ["tee", "tshirt"],
  ["trouser", "pants"],
  ["womens_clothing", "other"],
]);

function normalizeUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    url.hash = "";
    const removableParams = [
      "utm_source",
      "utm_medium",
      "utm_campaign",
      "utm_content",
      "utm_term",
      "fbclid",
      "gclid",
    ];
    for (const param of removableParams) url.searchParams.delete(param);
    url.pathname = url.pathname.replace(/\/+$/, "");
    return url.toString();
  } catch {
    return raw;
  }
}

function normalizeLookupId(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return "";
  return CLOTHING_TYPE_ALIASES.get(raw) || raw;
}

function isLikelyProductTitleLookup(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return false;
  if (raw.includes(" ")) return true;
  return raw.length > 32;
}

function toNumberOrNull(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function stableSha256(value) {
  return createHash("sha256").update(String(value)).digest("hex");
}

function fallbackReviewRowKey(row) {
  if (row.review_row_key) return { key: row.review_row_key, source: "workbook_review_row_key" };
  if (row.source_file && row.source_row_number) {
    return {
      key: stableSha256(`${row.source_file}:${row.source_row_number}`),
      source: "sha256_source_file_source_row_number",
    };
  }
  const productUrl = normalizeUrl(row.product_page_url_display || row.monetized_product_url_display);
  const imageUrl = normalizeUrl(row.image_url_to_use || row.raw_scraped_image_url || row.original_url_display);
  const fingerprint = [
    productUrl,
    imageUrl,
    row.source_site_display,
    row.user_comment,
    row.reviewer_name_raw,
    row.date_review_submitted_raw || row.review_date,
    row.size_display,
  ].join(":");
  return { key: stableSha256(fingerprint), source: "sha256_stable_fallback" };
}

function cropSpecFromDecision(decision) {
  const hasCrop =
    decision.crop_has_adjustment === true ||
    String(decision.crop_has_adjustment || "").toLowerCase() === "true";
  if (!hasCrop) return null;
  return {
    mode: decision.crop_mode || "object-position",
    aspectRatio: decision.crop_aspect_ratio || "3:4",
    objectPositionXPct: Number(decision.crop_object_position_x_pct || 50),
    objectPositionYPct: Number(decision.crop_object_position_y_pct || 50),
    zoom: Number(decision.crop_zoom || 1),
    rotationDeg: Number(decision.crop_rotation_deg || 0),
    source: "manual",
  };
}

function rowImageUrl(row) {
  return row.image_url_to_use || row.raw_scraped_image_url || row.original_url_display || "";
}

function rowProductUrl(row) {
  return row.product_page_url_display || row.monetized_product_url_display || "";
}

function rowReviewIdentity(row, reviewRowKey) {
  const productUrl = normalizeUrl(rowProductUrl(row));
  const sourceReviewId = row.source_review_id || row.review_id || "";
  if (productUrl && sourceReviewId) {
    return {
      key: `source:${productUrl}:${sourceReviewId}`,
      source: "source_review_id",
    };
  }

  const context = [
    row.reviewer_name_raw || row.reviewer_name || "",
    row.date_review_submitted_raw || row.review_date || "",
    row.user_comment || "",
  ].map((value) => String(value || "").trim());
  if (productUrl && context.some(Boolean)) {
    return {
      key: `context:${stableSha256([productUrl, ...context].join(":"))}`,
      source: "product_reviewer_date_comment",
    };
  }

  return {
    key: `row:${reviewRowKey}`,
    source: "review_row_key",
  };
}

function extractSourceReviewId(row) {
  return row.source_review_id || row.review_id || "";
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

function getCellText(row, columnNumber) {
  const cell = row.getCell(columnNumber);
  if (cell.value == null) return "";
  if (typeof cell.value === "object") {
    if ("text" in cell.value) return String(cell.value.text ?? "");
    if ("result" in cell.value) return String(cell.value.result ?? "");
    if ("formula" in cell.value) return "";
    if (cell.value.richText) return cell.value.richText.map((part) => part.text).join("");
    return String(cell.text ?? "");
  }
  return String(cell.value);
}

function getHeaders(sheet) {
  const headers = [];
  sheet.getRow(1).eachCell({ includeEmpty: true }, (cell, colNumber) => {
    headers[colNumber - 1] = String(cell.value ?? "").trim();
  });
  return headers;
}

function rowToObject(row, headers) {
  const object = {};
  headers.forEach((header, index) => {
    if (header) object[header] = getCellText(row, index + 1);
  });
  return object;
}

async function readWorkbookRow(packageDir, decision) {
  const filePath = path.join(packageDir, decision.part_file);
  if (!existsSync(filePath)) return { error: `Missing source workbook: ${filePath}` };
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);
  const sheet = workbook.worksheets[0];
  const headers = getHeaders(sheet);
  let found = null;
  sheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1 || found) return;
    const raw = rowToObject(row, headers);
    const rowKey = raw.review_row_key || `${raw.source_file || "unknown"}::${raw.source_row_number || rowNumber}`;
    if (rowKey === decision.review_row_key) {
      raw.__rowNumber = rowNumber;
      found = raw;
    }
  });
  return found ? { row: found } : { error: `Missing review_row_key ${decision.review_row_key} in ${decision.part_file}` };
}

async function readWorkbookRowsByPart(packageDir, partFile) {
  const filePath = path.join(packageDir, partFile);
  if (!existsSync(filePath)) return { error: `Missing source workbook: ${filePath}` };
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);
  const sheet = workbook.worksheets[0];
  const headers = getHeaders(sheet);
  const rowsByKey = new Map();
  sheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1) return;
    const raw = rowToObject(row, headers);
    const rowKey = raw.review_row_key || `${raw.source_file || "unknown"}::${raw.source_row_number || rowNumber}`;
    raw.__rowNumber = rowNumber;
    rowsByKey.set(rowKey, raw);
  });
  return { rowsByKey, rowCount: rowsByKey.size };
}

async function directoryHasFile(dirPath, filename) {
  return existsSync(path.join(dirPath, filename));
}

async function findCandidatePackageDirs(dataDir, primaryPackageDir) {
  const dirs = [];
  const addDir = (dirPath) => {
    const resolved = path.resolve(dirPath);
    if (!dirs.includes(resolved) && existsSync(resolved)) dirs.push(resolved);
  };

  addDir(primaryPackageDir);

  for (const rawDir of String(process.env.FWM_IMAGE_REVIEW_ADDITIONAL_PACKAGE_DIRS || "").split(":")) {
    if (rawDir.trim()) addDir(rawDir.trim());
  }

  const pendingDir = path.join(dataDir, "03_cv_annotated_pending_human_review");
  if (existsSync(pendingDir)) {
    for (const entry of await readdir(pendingDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const directDir = path.join(pendingDir, entry.name);
      const packageDir = path.join(directDir, "package");
      addDir(directDir);
      addDir(packageDir);
    }
  }

  return dirs;
}

async function readWorkbookRowsByPartAcrossDirs(packageDirs, partFile) {
  const matches = [];
  const missingDirs = [];
  for (const packageDir of packageDirs) {
    if (!(await directoryHasFile(packageDir, partFile))) {
      missingDirs.push(packageDir);
      continue;
    }
    const resolved = await readWorkbookRowsByPart(packageDir, partFile);
    if (resolved.error) {
      matches.push({ packageDir, error: resolved.error, rowsByKey: new Map(), rowCount: 0 });
    } else {
      matches.push({ packageDir, rowsByKey: resolved.rowsByKey, rowCount: resolved.rowCount });
    }
  }
  if (!matches.length) {
    return {
      error: `Missing source workbook ${partFile} in ${packageDirs.length} candidate package dirs`,
      matches,
      missingDirs,
    };
  }
  return { matches, missingDirs };
}

async function getDevImageCount(guard) {
  const { response } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "images",
    method: "GET",
    searchParams: { select: "id", limit: "1" },
    prefer: "count=exact",
  });
  const count = Number((response.headers.get("content-range") || "").split("/").at(-1));
  return Number.isFinite(count) ? count : null;
}

async function fetchAllDevImageUrlKeys(guard) {
  const urls = new Map();
  const pageSize = 1000;
  for (let offset = 0; ; offset += pageSize) {
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "images",
      method: "GET",
      searchParams: {
        select: "id,original_url_display,product_page_url_display",
        order: "id.asc",
        limit: String(pageSize),
        offset: String(offset),
      },
    });
    const rows = Array.isArray(data) ? data : [];
    for (const row of rows) {
      const key = normalizeUrl(row.original_url_display);
      if (key && !urls.has(key)) urls.set(key, row);
    }
    if (rows.length < pageSize) break;
  }
  return urls;
}

async function fetchAllDevReviewRowKeys(guard) {
  const keys = new Set();
  const pageSize = 1000;
  for (let offset = 0; ; offset += pageSize) {
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "images",
      method: "GET",
      searchParams: {
        select: "review_row_key",
        review_row_key: "not.is.null",
        order: "review_row_key.asc",
        limit: String(pageSize),
        offset: String(offset),
      },
    });
    const rows = Array.isArray(data) ? data : [];
    for (const row of rows) {
      if (row.review_row_key) keys.add(row.review_row_key);
    }
    if (rows.length < pageSize) break;
  }
  return keys;
}

async function fetchDevClothingTypeIds(guard) {
  const { data } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "clothing_types",
    method: "GET",
    searchParams: { select: "id", limit: "10000" },
  });
  return new Set((Array.isArray(data) ? data : []).map((row) => row.id));
}

async function planApprovedRows({ approvals, packageDirs, guard, latestReport }) {
  const byPartFile = new Map();
  for (const decision of approvals) {
    if (!decision.part_file) continue;
    if (!byPartFile.has(decision.part_file)) byPartFile.set(decision.part_file, []);
    byPartFile.get(decision.part_file).push(decision);
  }

  const devImageUrls = fetchDevUrls ? await fetchAllDevImageUrlKeys(guard) : new Map();
  const devReviewRowKeys = await fetchAllDevReviewRowKeys(guard);
  const devClothingTypeIds = await fetchDevClothingTypeIds(guard);
  const plannedRows = [];
  const missingSourceRows = [];
  const missingRequiredRows = [];
  const workbookStats = [];
  const clothingTypeIds = new Set();
  const missingClothingTypeIds = new Set();

  for (const [partFile, partDecisions] of byPartFile.entries()) {
    const resolved = await readWorkbookRowsByPartAcrossDirs(packageDirs, partFile);
    if (resolved.error) {
      for (const decision of partDecisions) {
        missingSourceRows.push({
          part_file: partFile,
          review_row_key: decision.review_row_key,
          reason: resolved.error,
        });
      }
      workbookStats.push({ part_file: partFile, decisions: partDecisions.length, resolved_rows: 0, error: resolved.error });
      continue;
    }
    workbookStats.push({
      part_file: partFile,
      decisions: partDecisions.length,
      matched_workbooks: resolved.matches.length,
      resolved_rows: resolved.matches.reduce((sum, match) => sum + match.rowCount, 0),
      package_dirs: resolved.matches.map((match) => match.packageDir),
      error_count: resolved.matches.filter((match) => match.error).length,
    });
    for (const decision of partDecisions) {
      let row = null;
      let sourcePackageDir = null;
      for (const match of resolved.matches) {
        row = match.rowsByKey.get(decision.review_row_key);
        if (row) {
          sourcePackageDir = match.packageDir;
          break;
        }
      }
      if (!row) {
        missingSourceRows.push({
          part_file: partFile,
          review_row_key: decision.review_row_key,
          reason: "review_row_key not found in workbook",
        });
        continue;
      }
      row.__sourcePackageDir = sourcePackageDir;
      const rowKey = fallbackReviewRowKey({ ...row, ...decision });
      const imageUrl = normalizeUrl(rowImageUrl(row));
      const productUrl = normalizeUrl(rowProductUrl(row));
      const rawClothingTypeId = normalizeLookupId(row.clothing_type_id);
      const clothingTypeId = isLikelyProductTitleLookup(rawClothingTypeId) ? "other" : rawClothingTypeId;
      if (clothingTypeId) {
        clothingTypeIds.add(clothingTypeId);
        if (!devClothingTypeIds.has(clothingTypeId)) missingClothingTypeIds.add(clothingTypeId);
      }
      const pregnancy = parseWeeksPregnant(row.user_comment);
      const reviewIdentity = rowReviewIdentity(row, rowKey.key);
      const cropSpec = cropSpecFromDecision(decision);
      const missing = [];
      if (!imageUrl) missing.push("image_url");
      if (!productUrl) missing.push("product_url");
      if (missing.length) {
        missingRequiredRows.push({
          part_file: partFile,
          review_row_key: decision.review_row_key,
          missing,
        });
      }
      plannedRows.push({
        decision,
        row,
        review_row_key: rowKey.key,
        review_row_key_source: rowKey.source,
        image_url: imageUrl,
        product_url: productUrl,
        source_site: row.source_site_display || row.source_site || "",
        source_review_id: extractSourceReviewId(row),
        clothing_type_id: clothingTypeId || null,
        raw_clothing_type_id: row.clothing_type_id || null,
        review_identity_key: reviewIdentity.key,
        review_identity_source: reviewIdentity.source,
        crop_spec: cropSpec,
        weeks_pregnant: pregnancy.weeks_pregnant,
        pregnancy_evidence: pregnancy.pregnancy_evidence,
        baseline_match: imageUrl ? devImageUrls.get(imageUrl) || null : null,
        measurements: (() => {
          // Override the workbook's measurement columns with corrected values
          // when this comment has an audit override; otherwise use the workbook.
          const ov = measurementOverrides ? measurementOverrides[commentId(row.user_comment)] : null;
          if (ov) measurementOverrideHits += 1;
          const m = ov ? { ...row, ...ov } : row;
          return {
            height_in_display: toNumberOrNull(m.height_in_display),
            weight_lbs_display: toNumberOrNull(m.weight_lbs_display || m.weight_lb),
            waist_in: toNumberOrNull(m.waist_in),
            hips_in_display: toNumberOrNull(m.hips_in_display),
            inseam_inches_display: toNumberOrNull(m.inseam_inches_display),
            bust_in_display: toNumberOrNull(m.bust_in_display),
            bra_band_in_display: toNumberOrNull(m.bra_band_in_display),
            bust_in_number_display: toNumberOrNull(m.bust_in_number_display),
            cupsize_display: m.cupsize_display || null,
          };
        })(),
      });
    }
  }

  const duplicateGroups = [];
  const byImageUrl = new Map();
  for (const planned of plannedRows) {
    if (!planned.image_url) continue;
    if (!byImageUrl.has(planned.image_url)) byImageUrl.set(planned.image_url, []);
    byImageUrl.get(planned.image_url).push(planned);
  }

  const actionCounts = {
    insert: 0,
    merge_into_baseline: 0,
    merge_into_existing_review_row_key: 0,
    merge_into_approved_canonical: 0,
    quarantine_duplicate_conflict: 0,
    skipped_missing_required: missingRequiredRows.length,
    skipped_missing_source: missingSourceRows.length,
  };
  const plannedActions = [];
  const duplicateConflictSamples = [];

  for (const group of byImageUrl.values()) {
    const baselineMatch = group.find((row) => row.baseline_match)?.baseline_match || null;
    const productUrls = new Set(group.map((row) => row.product_url).filter(Boolean));
    const reviewKeys = new Set(group.map((row) => row.review_identity_key).filter(Boolean));
    const hasMissingRequired = group.some((row) => !row.image_url || !row.product_url);
    if (baselineMatch) {
      for (const row of group) {
        actionCounts.merge_into_baseline += 1;
        plannedActions.push({ action: "merge_into_baseline", row, baseline_image_id: baselineMatch.id });
      }
      continue;
    }
    if (group.length > 1) {
      const conflict = productUrls.size > 1 || reviewKeys.size > 1;
      duplicateGroups.push({
        image_url: group[0].image_url,
        row_count: group.length,
        product_url_count: productUrls.size,
        review_identity_count: reviewKeys.size,
        conflict,
      });
      if (conflict || hasMissingRequired) {
        actionCounts.quarantine_duplicate_conflict += group.length;
        if (duplicateConflictSamples.length < 25) {
          duplicateConflictSamples.push({
            image_url: group[0].image_url,
            rows: group.slice(0, 5).map((row) => ({
              part_file: row.decision.part_file,
              review_row_key: row.decision.review_row_key,
              product_url: row.product_url,
              review_identity_key: row.review_identity_key,
            })),
          });
        }
        continue;
      }
      actionCounts.insert += 1;
      actionCounts.merge_into_approved_canonical += group.length - 1;
      plannedActions.push({ action: "insert", row: group[0] });
      for (const row of group.slice(1)) plannedActions.push({ action: "merge_into_approved_canonical", row });
      continue;
    }
    const row = group[0];
    if (!row.image_url || !row.product_url) continue;
    if (devReviewRowKeys.has(row.review_row_key)) {
      actionCounts.merge_into_existing_review_row_key += 1;
      plannedActions.push({ action: "merge_into_existing_review_row_key", row });
      continue;
    }
    actionCounts.insert += 1;
    plannedActions.push({ action: "insert", row });
  }

  return {
    latest_reconciliation_report: latestReport?.path || null,
    workbook_stats: workbookStats,
    planned_rows: plannedRows,
    planned_actions: plannedActions,
    missing_source_rows: missingSourceRows,
    missing_required_rows: missingRequiredRows,
    duplicate_groups: duplicateGroups,
    duplicate_conflict_samples: duplicateConflictSamples,
    distinct_clothing_type_ids: Array.from(clothingTypeIds).sort(),
    missing_clothing_type_ids: Array.from(missingClothingTypeIds).sort(),
    action_counts: actionCounts,
    existing_dev_image_url_count: devImageUrls.size,
    existing_dev_review_row_key_count: devReviewRowKeys.size,
    planned_action_review_row_key_count: new Set(planReviewRowKeys(plannedActions)).size,
    planned_action_missing_dev_review_row_key_count: planMissingReviewRowKeys(plannedActions, devReviewRowKeys).length,
    planned_action_missing_dev_review_row_key_samples: planMissingReviewRowKeys(plannedActions, devReviewRowKeys).slice(0, 50),
  };
}

function planReviewRowKeys(plannedActions) {
  return plannedActions.map((action) => action.row.review_row_key).filter(Boolean);
}

function planMissingReviewRowKeys(plannedActions, devReviewRowKeys) {
  const missing = [];
  const seen = new Set();
  for (const action of plannedActions) {
    const key = action.row.review_row_key;
    if (!key || seen.has(key) || devReviewRowKeys.has(key)) continue;
    seen.add(key);
    missing.push({
      action: action.action,
      review_row_key: key,
      image_url: action.row.image_url,
      product_url: action.row.product_url,
      baseline_image_id: action.baseline_image_id || action.row.baseline_match?.id || null,
    });
  }
  return missing;
}

function reviewedImagePayloadFromAction(action) {
  const row = action.row;
  const rpcAction = action.action === "merge_into_existing_review_row_key" ? "insert" : action.action;
  return {
    action: rpcAction,
    image_id: rpcAction === "insert" ? randomUUID() : null,
    baseline_image_id: action.baseline_image_id || null,
    image_url: row.image_url,
    normalized_product_page_url: row.product_url,
    monetized_product_url: normalizeUrl(row.row.monetized_product_url_display || ""),
    source_site: row.source_site || null,
    brand: row.row.brand || null,
    product_title_raw: row.row.product_title_raw || null,
    product_category_raw: row.row.product_category_raw || null,
    clothing_type_id: row.clothing_type_id,
    review_identity_key: row.review_identity_key,
    source_review_id: row.source_review_id || null,
    reviewer_name_raw: row.row.reviewer_name_raw || null,
    review_date_raw: row.row.date_review_submitted_raw || row.row.review_date || null,
    user_comment: row.row.user_comment || null,
    source_file: row.row.source_file || row.decision.part_file || null,
    source_row_number: row.row.source_row_number || null,
    review_row_key: row.review_row_key,
    crop_spec: row.crop_spec,
    full_body_visible: null,
    weeks_pregnant: row.weeks_pregnant,
    pregnancy_evidence: row.pregnancy_evidence,
    height_in_display: row.measurements.height_in_display,
    weight_lbs_display: row.measurements.weight_lbs_display,
    waist_in: row.measurements.waist_in,
    hips_in_display: row.measurements.hips_in_display,
    inseam_inches_display: row.measurements.inseam_inches_display,
    bust_in_display: row.measurements.bust_in_display,
    bra_band_in_display: row.measurements.bra_band_in_display,
    bust_in_number_display: row.measurements.bust_in_number_display,
    cupsize_display: row.measurements.cupsize_display,
    size_display: row.row.size_display || "unknown",
  };
}

async function applyReviewedImagePlan({ guard, plan }) {
  const writableActions = plan.planned_actions.filter((action) =>
    action.action === "insert" ||
      action.action === "merge_into_existing_review_row_key" ||
      action.action === "merge_into_baseline",
  );
  const batches = [];
  for (let index = 0; index < writableActions.length; index += batchSize) {
    batches.push(writableActions.slice(index, index + batchSize));
  }

  const totals = {
    input_count: 0,
    product_pages_upserted: 0,
    reviews_upserted: 0,
    images_inserted: 0,
    images_updated: 0,
    batch_count: batches.length,
  };

  for (const [batchIndex, batch] of batches.entries()) {
    const payload = batch.map(reviewedImagePayloadFromAction);
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "rpc/dev_upsert_reviewed_image_batch",
      method: "POST",
      body: { payload },
    });
    const result = Array.isArray(data) ? data[0] : data;
    if (!result) throw new Error(`Loader RPC returned no result for batch ${batchIndex + 1}`);
    totals.input_count += Number(result.input_count || 0);
    totals.product_pages_upserted += Number(result.product_pages_upserted || 0);
    totals.reviews_upserted += Number(result.reviews_upserted || 0);
    totals.images_inserted += Number(result.images_inserted || 0);
    totals.images_updated += Number(result.images_updated || 0);
    console.log(`Applied loader batch ${batchIndex + 1}/${batches.length}: ${payload.length} rows`);
  }

  return totals;
}

async function latestReconciliationReport(reportsDir) {
  if (!existsSync(reportsDir)) return null;
  const files = (await readdir(reportsDir))
    .filter((filename) => /^mobile_review_reconciliation_state_.*\.json$/.test(filename))
    .sort();
  if (!files.length) return null;
  const filename = files.at(-1);
  return { filename, path: path.join(reportsDir, filename), report: await readJson(path.join(reportsDir, filename)) };
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Approved-images loader guard" });

  const dataDir = fwmDataDir(repoRoot);
  const packageDir = process.env.FWM_IMAGE_REVIEW_PACKAGE_DIR || defaultImageReviewPackageDir(repoRoot);
  const returnsDir = process.env.FWM_IMAGE_REVIEW_RETURNS_DIR || defaultImageReviewReturnsDir(repoRoot);
  const reportsDir = path.join(dataDir, "_reports");
  const manifestPath = path.join(returnsDir, "human_labeled_returns_manifest.json");
  const manifest = await readJson(manifestPath);
  const decisions = Object.values(manifest.decisions || {});
  const approvals = decisions.filter((d) => d.production_decision === "APPROVE" || d.human_state === "APPROVE");
  const duplicateReviewRowKeys = approvals.length - new Set(approvals.map((d) => d.review_row_key).filter(Boolean)).size;
  const latestReport = await latestReconciliationReport(reportsDir);
  const devImageCount = await getDevImageCount(guard);

  const summary = {
    generated_at: new Date().toISOString(),
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    data_dir: dataDir,
    package_dir: packageDir,
    package_dirs: [],
    returns_dir: returnsDir,
    manifest_path: manifestPath,
    latest_reconciliation_report: latestReport?.path || null,
    reconciliation_all_clear: Boolean(
      latestReport &&
        latestReport.report.unmerged_file_count === 0 &&
        latestReport.report.unmerged_decision_count === 0,
    ),
    current_dev_images_count: devImageCount,
    total_manifest_decisions: decisions.length,
    approved_manifest_decisions: approvals.length,
    duplicate_review_row_key_count: duplicateReviewRowKeys,
    crop_adjusted_approved_rows: approvals.filter((d) => cropSpecFromDecision(d)).length,
    missing_source_workbook_reference_count: approvals.filter((d) => !d.bucket || !d.part_file || !d.review_row_key).length,
    workbook_resolution_enabled: resolveWorkbooks,
    workbook_resolution_sample_limit: resolveWorkbooks ? sampleLimit : 0,
    sample_rows: [],
    load_plan: null,
    apply_result: null,
    planned_write_tables: [
      "public.clothing_types",
      "staging.product_pages",
      "public.reviews",
      "public.images",
    ],
  };
  let resolvedPlan = null;

  if (resolveWorkbooks) {
    const packageDirs = await findCandidatePackageDirs(dataDir, packageDir);
    summary.package_dirs = packageDirs;
    const plan = await planApprovedRows({ approvals, packageDirs, guard, latestReport });
    resolvedPlan = plan;
    summary.load_plan = {
      source_workbooks_scanned: plan.workbook_stats.length,
      workbook_error_count: plan.workbook_stats.filter((item) => item.error).length,
      existing_dev_image_url_count: plan.existing_dev_image_url_count,
      planned_row_count: plan.planned_rows.length,
      planned_action_counts: plan.action_counts,
      existing_dev_review_row_key_count: plan.existing_dev_review_row_key_count,
      planned_action_review_row_key_count: plan.planned_action_review_row_key_count,
      planned_action_missing_dev_review_row_key_count: plan.planned_action_missing_dev_review_row_key_count,
      planned_action_missing_dev_review_row_key_samples: plan.planned_action_missing_dev_review_row_key_samples,
      duplicate_image_url_group_count: plan.duplicate_groups.length,
      duplicate_conflict_group_count: plan.duplicate_groups.filter((group) => group.conflict).length,
      missing_source_row_count: plan.missing_source_rows.length,
      missing_required_row_count: plan.missing_required_rows.length,
      distinct_clothing_type_ids: plan.distinct_clothing_type_ids,
      missing_clothing_type_ids: plan.missing_clothing_type_ids,
      quarantine_required: plan.action_counts.quarantine_duplicate_conflict > 0,
      duplicate_conflict_samples: plan.duplicate_conflict_samples,
      missing_source_samples: plan.missing_source_rows.slice(0, 50),
      missing_required_samples: plan.missing_required_rows.slice(0, 50),
      measurement_override_file: measurementOverridesPath || null,
      measurement_override_rows_applied: measurementOverrideHits,
    };
    summary.sample_rows = plan.planned_actions.slice(0, Math.max(0, sampleLimit)).map(({ action, row }) => ({
      action,
      review_row_key: row.decision.review_row_key,
      planned_review_row_key: row.review_row_key,
      planned_review_row_key_source: row.review_row_key_source,
      review_identity_key: row.review_identity_key,
      review_identity_source: row.review_identity_source,
      normalized_product_url: row.product_url,
      image_url: row.image_url,
      baseline_match_id: row.baseline_match?.id || null,
      clothing_type_id: row.clothing_type_id,
      crop_spec: row.crop_spec,
      weeks_pregnant: row.weeks_pregnant,
      pregnancy_evidence: row.pregnancy_evidence,
      measurements: row.measurements,
    }));
  }

  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_approved_images_loader_dry_run_${summary.generated_at.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`);
  await writeFile(reportPath, JSON.stringify(summary, null, 2) + "\n", "utf8");

  console.log(`Wrote loader report: ${reportPath}`);
  console.log(`Mode: ${summary.mode}`);
  console.log(`Resolved Supabase: ${summary.supabase_url} (${summary.supabase_project_ref})`);
  console.log(`Current dev public.images count: ${summary.current_dev_images_count ?? "unknown"}`);
  console.log(`Approved manifest decisions: ${summary.approved_manifest_decisions}`);
  console.log(`Latest reconciliation all clear: ${summary.reconciliation_all_clear}`);
  console.log(`Planned write tables: ${summary.planned_write_tables.join(", ")}`);
  if (summary.load_plan) {
    console.log(`Source workbooks scanned: ${summary.load_plan.source_workbooks_scanned}`);
    console.log(`Planned rows resolved: ${summary.load_plan.planned_row_count}`);
    console.log(`Planned action counts: ${JSON.stringify(summary.load_plan.planned_action_counts)}`);
    console.log(`Duplicate image URL groups: ${summary.load_plan.duplicate_image_url_group_count}`);
    console.log(`Duplicate conflict groups: ${summary.load_plan.duplicate_conflict_group_count}`);
    console.log(`Missing source rows: ${summary.load_plan.missing_source_row_count}`);
    console.log(`Missing required rows: ${summary.load_plan.missing_required_row_count}`);
    console.log(`Missing clothing type ids: ${summary.load_plan.missing_clothing_type_ids.join(", ") || "none"}`);
  }

  if (!summary.reconciliation_all_clear) {
    const message = "Write mode is blocked until the latest reconciliation report has zero unmerged files and decisions.";
    if (apply) throw new Error(message);
    console.log(message);
  }
  if (summary.load_plan?.quarantine_required) {
    const message = "Write mode is blocked until duplicate conflicts are reviewed or explicitly skipped.";
    if (apply && !skipDuplicateConflicts) throw new Error(`${message} To skip quarantined duplicate conflicts for this dev load, rerun with FWM_DEV_IMAGE_LOAD_SKIP_DUPLICATE_CONFLICTS=yes-reviewed-dry-run after reviewing the dry-run report.`);
    console.log(message);
    if (apply && skipDuplicateConflicts) {
      console.log("Duplicate conflicts will be skipped in apply mode because FWM_DEV_IMAGE_LOAD_SKIP_DUPLICATE_CONFLICTS=yes-reviewed-dry-run is set.");
    }
  }
  if (summary.load_plan?.missing_clothing_type_ids?.length) {
    const message = "Write mode is blocked until missing clothing type lookup ids are seeded or upserted.";
    if (apply) throw new Error(message);
    console.log(message);
  }

  if (!apply) {
    console.log("Dry-run only. No Supabase rows were written.");
    return;
  }

  requireExplicitWriteFlag();
  if (!resolveWorkbooks || !resolvedPlan) {
    throw new Error("Write mode requires --resolve-workbooks so source rows, duplicates, and lookups are validated first.");
  }
  summary.apply_result = await applyReviewedImagePlan({ guard, plan: resolvedPlan });
  await writeFile(reportPath, JSON.stringify(summary, null, 2) + "\n", "utf8");
  console.log(`Apply result: ${JSON.stringify(summary.apply_result)}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
