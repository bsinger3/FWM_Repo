import ExcelJS from "exceljs";
import JSZip from "jszip";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile, unlink, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const toolDir = path.dirname(__filename);
const repoRoot = path.resolve(toolDir, "../..");
const publicDir = path.join(toolDir, "public");
const packageDir =
  process.env.FWM_IMAGE_REVIEW_PACKAGE_DIR ||
  path.join(
    repoRoot,
    "outputs/02_supabase_needs_human_review_cv_first_pass/partial_170000_rows_cv_gated",
  );
const returnsDir =
  process.env.FWM_IMAGE_REVIEW_RETURNS_DIR ||
  path.join(repoRoot, "outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns");
const manifestPath = path.join(returnsDir, "human_labeled_returns_manifest.json");
const eligibleIndexPath = path.join(returnsDir, "image_review_eligible_index.json");
const cropReturnHeaders = [
  "crop_has_adjustment",
  "crop_mode",
  "crop_aspect_ratio",
  "crop_object_position_x_pct",
  "crop_object_position_y_pct",
  "crop_zoom",
  "crop_rotation_deg",
];
let checkpointCommentCachePromise = null;
const eligibleRowCountCache = new Map();
let eligibleIndexPromise = null;

const imageFieldNames = ["image_url_to_use", "raw_scraped_image_url"];
const measurementFieldNames = [
  "weight_lbs_display",
  "weight_display_display",
  "weight_lbs",
  "waist_in",
  "waist_in_display",
  "hips_in_display",
  "hips_in",
  "bust_in_display",
  "bust_in_number_display",
  "bust_in",
  "bra_band_in_display",
  "bra_band_in",
  "cupsize_display",
  "cup_size",
  "inseam_inches_display",
  "inseam_in",
];
const rowKeyFieldNames = ["review_row_key", "source_file", "source_row_number"];
const packageRowTotals = {
  approve_candidates: 72113,
  needs_human_review: 40170,
  disapprove_candidates: 211918,
};
const reviewWorkbookPartSize = 1000;

const bucketConfig = {
  approve_candidates: {
    label: "Approve Candidates",
    defaultDecision: "APPROVE",
    pattern: /^supabase_image_review_approve_candidates_part_(\d{3})\.xlsx$/,
  },
  needs_human_review: {
    label: "Needs Human Review",
    defaultDecision: "NEEDS_HUMAN_REVIEW",
    pattern: /^supabase_image_review_needs_human_review_part_(\d{3})\.xlsx$/,
  },
  disapprove_candidates: {
    label: "Disapprove Candidates",
    defaultDecision: "DISAPPROVE",
    pattern: /^supabase_image_review_disapprove_candidates_part_(\d{3})\.xlsx$/,
  },
};

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
};

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data, null, 2);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store, max-age=0",
  });
  res.end(body);
}

function sendError(res, message, status = 500) {
  sendJson(res, { error: message }, status);
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function readManifest() {
  if (!existsSync(manifestPath)) {
    return {
      package_id: "partial_170000_rows_cv_gated",
      source_folder: packageDir,
      return_folder: returnsDir,
      exports: [],
      decisions: {},
    };
  }
  const raw = await readFile(manifestPath, "utf8");
  const parsed = JSON.parse(raw);
  parsed.exports ||= [];
  parsed.decisions ||= {};
  return parsed;
}

async function writeManifest(manifest) {
  await mkdir(returnsDir, { recursive: true });
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
}

async function readEligibleIndex() {
  if (!eligibleIndexPromise) {
    eligibleIndexPromise = (async () => {
      if (!existsSync(eligibleIndexPath)) return null;
      const parsed = JSON.parse(await readFile(eligibleIndexPath, "utf8"));
      return parsed.package_dir === packageDir ? parsed : null;
    })();
  }
  return eligibleIndexPromise;
}

function getBucketAndPartFromFile(filename) {
  for (const [bucket, config] of Object.entries(bucketConfig)) {
    const match = filename.match(config.pattern);
    if (match) {
      return { bucket, partNumber: Number(match[1]), part: match[1] };
    }
  }
  return null;
}

async function getWorksheetRowCountFast(filePath) {
  const bytes = await readFile(filePath);
  const zip = await JSZip.loadAsync(bytes);
  const sheetXml = await zip.file("xl/worksheets/sheet1.xml")?.async("string");
  if (!sheetXml) return 0;
  const dimension = sheetXml.match(/<dimension[^>]*\sref="[^"]*?(\d+)(?::[^"]*?(\d+))?"/);
  if (dimension) {
    return Math.max(Number(dimension[2] || dimension[1]) - 1, 0);
  }
  const rowMatches = sheetXml.match(/<row\b/g) || [];
  return Math.max(rowMatches.length - 1, 0);
}

function decodeXmlText(value = "") {
  return String(value)
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function columnLettersToIndex(letters = "") {
  let index = 0;
  for (const letter of letters.toUpperCase()) {
    index = index * 26 + (letter.charCodeAt(0) - 64);
  }
  return index;
}

function parseSharedStrings(sharedStringsXml = "") {
  const strings = [];
  const itemPattern = /<si\b[^>]*>([\s\S]*?)<\/si>/g;
  let match;
  while ((match = itemPattern.exec(sharedStringsXml))) {
    const textParts = Array.from(match[1].matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g), (part) =>
      decodeXmlText(part[1]),
    );
    strings.push(textParts.join(""));
  }
  return strings;
}

function getXmlAttribute(attributes, name) {
  return attributes.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1] || "";
}

function getCellXmlText(attributes, body, sharedStrings) {
  const type = getXmlAttribute(attributes, "t");
  if (type === "inlineStr") {
    const textParts = Array.from(body.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g), (part) => decodeXmlText(part[1]));
    return textParts.join("");
  }
  const value = body.match(/<v\b[^>]*>([\s\S]*?)<\/v>/)?.[1] || "";
  if (type === "s") return sharedStrings[Number(value)] || "";
  return decodeXmlText(value);
}

function getCellColumnIndex(attributes) {
  const ref = getXmlAttribute(attributes, "r");
  const letters = ref.match(/^[A-Z]+/i)?.[0] || "";
  return columnLettersToIndex(letters);
}

function hasAnyFieldValue(raw, fieldNames) {
  return fieldNames.some((fieldName) => String(raw[fieldName] || "").trim());
}

function getRawRowKey(raw, rowNumber) {
  return raw.review_row_key || `${raw.source_file || "unknown"}::${raw.source_row_number || rowNumber}`;
}

function isDashboardEligibleRaw(raw) {
  return hasAnyFieldValue(raw, imageFieldNames) && hasAnyFieldValue(raw, measurementFieldNames);
}

function estimatePartRowCount(bucket, partIndex, partCount) {
  const total = packageRowTotals[bucket];
  if (!total) return reviewWorkbookPartSize;
  if (partIndex < partCount - 1) return Math.min(reviewWorkbookPartSize, Math.max(total - partIndex * reviewWorkbookPartSize, 0));
  return Math.max(total - partIndex * reviewWorkbookPartSize, 0);
}

async function getEligibleWorksheetSummaryFast(filePath) {
  if (eligibleRowCountCache.has(filePath)) return eligibleRowCountCache.get(filePath);

  const summaryPromise = (async () => {
    const bytes = await readFile(filePath);
    const zip = await JSZip.loadAsync(bytes);
    const sheetXml = await zip.file("xl/worksheets/sheet1.xml")?.async("string");
    if (!sheetXml) return { rowCount: 0, rowKeys: new Set() };

    const sharedStringsXml = await zip.file("xl/sharedStrings.xml")?.async("string");
    const sharedStrings = parseSharedStrings(sharedStringsXml || "");
    const rows = Array.from(sheetXml.matchAll(/<row\b([^>]*)>([\s\S]*?)<\/row>/g), (match, index) => ({
      attributes: match[1],
      body: match[2],
      rowNumber: Number(getXmlAttribute(match[1], "r")) || index + 1,
    }));
    if (rows.length < 2) return { rowCount: 0, rowKeys: new Set() };

    const headersByColumn = new Map();
    const headerCells = rows[0].body.matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/g);
    for (const cell of headerCells) {
      const columnIndex = getCellColumnIndex(cell[1]);
      if (!columnIndex) continue;
      const header = getCellXmlText(cell[1], cell[2], sharedStrings).trim();
      if (header) headersByColumn.set(columnIndex, header);
    }

    const relevantColumns = new Map();
    const relevantFields = new Set([...imageFieldNames, ...measurementFieldNames, ...rowKeyFieldNames]);
    for (const [columnIndex, header] of headersByColumn.entries()) {
      if (relevantFields.has(header)) relevantColumns.set(columnIndex, header);
    }
    if (relevantColumns.size === 0) return { rowCount: 0, rowKeys: new Set() };

    const rowKeys = new Set();
    for (const rowInfo of rows.slice(1)) {
      const raw = {};
      const cells = rowInfo.body.matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/g);
      for (const cell of cells) {
        const columnIndex = getCellColumnIndex(cell[1]);
        const header = relevantColumns.get(columnIndex);
        if (!header) continue;
        raw[header] = getCellXmlText(cell[1], cell[2], sharedStrings);
      }
      if (isDashboardEligibleRaw(raw)) rowKeys.add(getRawRowKey(raw, rowInfo.rowNumber));
    }
    return { rowCount: rowKeys.size, rowKeys };
  })();

  eligibleRowCountCache.set(filePath, summaryPromise);
  return summaryPromise;
}

async function listParts() {
  const { readdir } = await import("node:fs/promises");
  const files = await readdir(packageDir);
  const manifest = await readManifest();
  const manifestLookup = buildManifestLookup(manifest);
  const eligibleIndex = await readEligibleIndex();
  const savedCountsByBucket = {};
  const savedCountsByPart = {};
  const savedCountsByExport = {};
  for (const decision of Object.values(manifest.decisions)) {
    savedCountsByBucket[decision.bucket] = (savedCountsByBucket[decision.bucket] || 0) + 1;
    const partKey = `${decision.bucket}::${decision.part_file}`;
    savedCountsByPart[partKey] = (savedCountsByPart[partKey] || 0) + 1;
    if (decision.export_stamp) {
      savedCountsByExport[decision.export_stamp] = (savedCountsByExport[decision.export_stamp] || 0) + 1;
    }
  }
  const buckets = Object.fromEntries(
    Object.entries(bucketConfig).map(([bucket, config]) => [
      bucket,
      {
        bucket,
        label: config.label,
        defaultDecision: config.defaultDecision,
        rowCount: 0,
        savedRowCount: 0,
        remainingRowCount: 0,
        remainingPartCount: 0,
        parts: [],
      },
    ]),
  );

  const filesByBucket = new Map();
  for (const filename of files) {
    const parsed = getBucketAndPartFromFile(filename);
    if (!parsed) continue;
    const entries = filesByBucket.get(parsed.bucket) || [];
    entries.push({ ...parsed, filename });
    filesByBucket.set(parsed.bucket, entries);
  }

  for (const [bucket, entries] of filesByBucket.entries()) {
    entries.sort((a, b) => a.partNumber - b.partNumber);
    for (const [partIndex, entry] of entries.entries()) {
      const filename = entry.filename;
      const indexedPart = eligibleIndex?.parts?.[filename] || null;
      const rowKeys = indexedPart?.row_keys || null;
      const rowCount = indexedPart ? Number(indexedPart.row_count || 0) : estimatePartRowCount(bucket, partIndex, entries.length);
      let savedRowCount = savedCountsByPart[`${bucket}::${filename}`] || 0;
      if (rowKeys) {
        savedRowCount = rowKeys.reduce(
          (count, rowKey) =>
            count + (manifest.decisions[getDecisionKey(bucket, filename, rowKey)] || manifestLookup.byRowKey.has(rowKey) ? 1 : 0),
          0,
        );
      }
      const remainingRowCount = Math.max(rowCount - savedRowCount, 0);
      buckets[bucket].rowCount += rowCount;
      buckets[bucket].savedRowCount += savedRowCount;
      buckets[bucket].remainingRowCount += remainingRowCount;
      if (remainingRowCount > 0) buckets[bucket].remainingPartCount += 1;
      buckets[bucket].parts.push({
        part: entry.part,
        partNumber: entry.partNumber,
        filename,
        rowCount,
        savedRowCount,
        remainingRowCount,
      });
    }
  }

  for (const bucket of Object.values(buckets)) {
    bucket.parts.sort((a, b) => a.partNumber - b.partNumber);
  }

  const latestExport = manifest.exports.at(-1) || null;

  return {
    packageId: "partial_170000_rows_cv_gated",
    packageDir,
    returnsDir,
    manifestExists: existsSync(manifestPath),
    savedCountsByBucket,
    latestExport: latestExport
      ? {
          exportStamp: latestExport.export_stamp,
          exportedAt: latestExport.exported_at,
          workbookCount: (latestExport.output_workbooks || []).length,
          decisionCount: savedCountsByExport[latestExport.export_stamp] || 0,
        }
      : null,
    buckets,
  };
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
  const headerRow = sheet.getRow(1);
  const headers = [];
  headerRow.eachCell({ includeEmpty: true }, (cell, colNumber) => {
    headers[colNumber - 1] = String(cell.value ?? "").trim();
  });
  return headers;
}

function getRowObject(row, headers) {
  const object = {};
  headers.forEach((header, index) => {
    if (!header) return;
    object[header] = getCellText(row, index + 1);
  });
  return object;
}

function getDecisionKey(bucket, partFile, rowKey) {
  return `${bucket}::${partFile}::${rowKey}`;
}

function sourceDecisionKey(sourceFile, sourceRowNumber) {
  const sourceKey = `${sourceFile || ""}::${sourceRowNumber || ""}`;
  return sourceKey === "::" ? "" : sourceKey;
}

function buildManifestLookup(manifest) {
  const byRowKey = new Map();
  const bySource = new Map();
  for (const decision of Object.values(manifest.decisions || {})) {
    if (decision.review_row_key && !byRowKey.has(decision.review_row_key)) {
      byRowKey.set(decision.review_row_key, decision);
    }
    const sourceKey = sourceDecisionKey(decision.source_file, decision.source_row_number);
    if (sourceKey && !bySource.has(sourceKey)) bySource.set(sourceKey, decision);
  }
  return { byRowKey, bySource };
}

function findSavedDecision(manifest, lookup, bucket, partFile, rowKey, sourceFile, sourceRowNumber) {
  return (
    manifest.decisions[getDecisionKey(bucket, partFile, rowKey)] ||
    lookup.byRowKey.get(rowKey) ||
    lookup.bySource.get(sourceDecisionKey(sourceFile, sourceRowNumber)) ||
    null
  );
}

function mapHumanState(productionDecision) {
  const normalized = String(productionDecision || "").trim().toUpperCase();
  if (["APPROVE", "APPROVED", "YES"].includes(normalized)) return "APPROVE";
  if (["DISAPPROVE", "REJECT", "REJECTED", "NO"].includes(normalized)) return "DISAPPROVE";
  return "NEUTRAL";
}

function normalizeDisplayRow(raw, bucket, part, partFile, defaultDecision, savedDecision, checkpointComments) {
  const rowKey =
    raw.review_row_key ||
    `${raw.source_file || "unknown"}::${raw.source_row_number || raw.__rowNumber}`;
  const productionDecision = savedDecision?.production_decision ?? raw.production_decision ?? "";
  const rejectionReason = savedDecision?.rejection_reason ?? raw.rejection_reason ?? "";
  const reviewNotes = savedDecision?.review_notes ?? raw.review_notes ?? "";
  const humanState = savedDecision ? mapHumanState(productionDecision) : "NEUTRAL";
  const cropAdjustment = normalizeCropAdjustment(savedDecision || raw);
  const shiftedSourceFields = hasShiftedSourceFields(raw);
  const sourceFile = shiftedSourceFields ? raw.user_comment : raw.source_file || "";
  const sourceRowNumber = shiftedSourceFields ? raw.source_file : raw.source_row_number || "";
  const userComment =
    shiftedSourceFields && checkpointComments?.has(rowKey)
      ? checkpointComments.get(rowKey)
      : raw.user_comment || "";

  return {
    bucket,
    packageId: "partial_170000_rows_cv_gated",
    partNumber: Number(part),
    partFile,
    rowNumber: raw.__rowNumber,
    rowKey,
    imageUrl: raw.image_url_to_use || raw.raw_scraped_image_url || "",
    rawImageUrl: raw.raw_scraped_image_url || "",
    productUrl: raw.product_page_url_display || "",
    monetizedProductUrl: raw.monetized_product_url_display || "",
    defaultDecision,
    humanState,
    productionDecision,
    rejectionReason,
    reviewNotes,
    cropAdjustment,
    savedDecisionState: savedDecision ? "saved" : "unsaved",
    reviewedAt: savedDecision?.reviewed_at || "",
    cvDecision: raw.cv_decision || "",
    cvReasonCode: raw.cv_reason_code || "",
    cvReasonSummary: raw.cv_reason_summary || "",
    sorterRecommendation: raw.sorter_recommendation || "",
    sorterReasonCodes: raw.sorter_reason_codes || "",
    cvMetrics: {
      person_count_yolo_detect: raw.person_count_yolo_detect || "",
      main_person_height_pct_yolo_detect: raw.main_person_height_pct_yolo_detect || "",
      main_person_bbox_area_pct_yolo_detect: raw.main_person_bbox_area_pct_yolo_detect || "",
      body_coverage_score_yolo_pose: raw.body_coverage_score_yolo_pose || "",
      has_face_yunet: raw.has_face_yunet || "",
    },
    display: {
      size: raw.size_display || "",
      colorOrVariant: raw.product_variant_raw || raw.color_display || "",
      clothingType: raw.clothing_type_id || "",
      heightIn: raw.height_in_display || "",
      weightLbs: raw.weight_lbs_display || raw.weight_display_display || "",
      waistIn: raw.waist_in || "",
      hipsIn: raw.hips_in_display || "",
      bustIn: raw.bust_in_display || raw.bust_in_number_display || "",
      braBandIn: raw.bra_band_in_display || "",
      cupSize: raw.cupsize_display || "",
      inseamIn: raw.inseam_inches_display || "",
      userComment,
      productTitle: raw.product_title_raw || "",
      productCategory: raw.product_category_raw || "",
    },
    source: {
      sourceFamily: raw.source_family || "",
      sourceSite: raw.source_site_display || "",
      sourceFile,
      sourceRowNumber,
    },
  };
}

function hasShiftedSourceFields(raw) {
  return isSourceCsvPath(raw.user_comment) && /^\d+$/.test(String(raw.source_file || ""));
}

function isSourceCsvPath(value) {
  return /\/step_1_raw_scraping_data\/.+\.csv$/.test(String(value || ""));
}

async function readCheckpointCommentCache() {
  if (!checkpointCommentCachePromise) {
    checkpointCommentCachePromise = buildCheckpointCommentCache();
  }
  return checkpointCommentCachePromise;
}

async function buildCheckpointCommentCache() {
  const checkpointDir = path.join(packageDir, "cv_gate_checkpoint_parts");
  const commentsByRowKey = new Map();
  if (!existsSync(checkpointDir)) return commentsByRowKey;

  const files = (await readdir(checkpointDir)).filter((filename) => filename.endsWith(".csv"));
  for (const filename of files) {
    const csv = await readFile(path.join(checkpointDir, filename), "utf8");
    const records = parseCsvRecords(csv);
    if (records.length < 2) continue;
    const headers = records[0];
    const rowKeyIndex = headers.indexOf("review_row_key");
    const commentIndex = headers.indexOf("user_comment");
    if (rowKeyIndex === -1 || commentIndex === -1) continue;
    for (const record of records.slice(1)) {
      const rowKey = record[rowKeyIndex];
      const comment = record[commentIndex];
      if (rowKey && comment && !isSourceCsvPath(comment)) commentsByRowKey.set(rowKey, comment);
    }
  }
  return commentsByRowKey;
}

function parseCsvRecords(csv) {
  const records = [];
  let record = [];
  let field = "";
  let inQuotes = false;

  for (let index = 0; index < csv.length; index += 1) {
    const char = csv[index];
    const next = csv[index + 1];
    if (char === '"') {
      if (inQuotes && next === '"') {
        field += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      record.push(field);
      field = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") index += 1;
      record.push(field);
      if (record.some((value) => value !== "")) records.push(record);
      record = [];
      field = "";
    } else {
      field += char;
    }
  }

  if (field || record.length) {
    record.push(field);
    records.push(record);
  }
  return records;
}

async function readWorkbookRows(bucket, part) {
  const config = bucketConfig[bucket];
  if (!config) throw new Error(`Unknown bucket: ${bucket}`);
  const partString = String(part || "001").padStart(3, "0");
  const filename = Object.keys(bucketConfig).reduce((name, candidateBucket) => {
    if (candidateBucket !== bucket) return name;
    if (bucket === "approve_candidates") {
      return `supabase_image_review_approve_candidates_part_${partString}.xlsx`;
    }
    if (bucket === "needs_human_review") {
      return `supabase_image_review_needs_human_review_part_${partString}.xlsx`;
    }
    return `supabase_image_review_disapprove_candidates_part_${partString}.xlsx`;
  }, "");
  const filePath = path.join(packageDir, filename);
  if (!existsSync(filePath)) throw new Error(`Workbook not found: ${filename}`);

  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);
  const sheet = workbook.worksheets[0];
  const headers = getHeaders(sheet);
  const manifest = await readManifest();
  const manifestLookup = buildManifestLookup(manifest);
  const checkpointComments = await readCheckpointCommentCache();
  const rows = [];

  sheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1) return;
    const raw = getRowObject(row, headers);
    raw.__rowNumber = rowNumber;
    if (!isDashboardEligibleRaw(raw)) return;
    const rowKey = getRawRowKey(raw, rowNumber);
    const shiftedSourceFields = hasShiftedSourceFields(raw);
    const sourceFile = shiftedSourceFields ? raw.user_comment : raw.source_file || "";
    const sourceRowNumber = shiftedSourceFields ? raw.source_file : raw.source_row_number || "";
    const savedDecision = findSavedDecision(
      manifest,
      manifestLookup,
      bucket,
      filename,
      rowKey,
      sourceFile,
      sourceRowNumber,
    );
    rows.push(
      normalizeDisplayRow(
        raw,
        bucket,
        partString,
        filename,
        config.defaultDecision,
        savedDecision,
        checkpointComments,
      ),
    );
  });

  const reasonSheet = workbook.worksheets[1];
  const rejectionReasons = [];
  if (reasonSheet) {
    reasonSheet.eachRow((row, rowNumber) => {
      if (rowNumber === 1) return;
      const reason = getCellText(row, 1);
      if (reason) rejectionReasons.push(reason);
    });
  }

  return {
    bucket,
    label: config.label,
    part: partString,
    filename,
    defaultDecision: config.defaultDecision,
    headers,
    rejectionReasons,
    rows,
  };
}

function sanitizeTimestamp(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function normalizeCropAdjustment(value = {}) {
  const source = value || {};
  const raw = source.cropAdjustment || source.crop_adjustment || source;
  const x = Number(raw.cropObjectPositionXPct ?? raw.crop_object_position_x_pct ?? 50);
  const y = Number(raw.cropObjectPositionYPct ?? raw.crop_object_position_y_pct ?? 50);
  const zoom = Number(raw.cropZoom ?? raw.crop_zoom ?? 1);
  const rotation = Number(raw.cropRotationDeg ?? raw.crop_rotation_deg ?? 0);
  const hasCropAdjustment =
    raw.hasCropAdjustment === true ||
    raw.crop_has_adjustment === true ||
    String(raw.crop_has_adjustment || "").toLowerCase() === "true";
  return {
    hasCropAdjustment,
    cropMode: raw.cropMode || raw.crop_mode || "object-position",
    cropAspectRatio: raw.cropAspectRatio || raw.crop_aspect_ratio || "3:4",
    cropObjectPositionXPct: Number.isFinite(x) ? Math.min(100, Math.max(0, x)) : 50,
    cropObjectPositionYPct: Number.isFinite(y) ? Math.min(100, Math.max(0, y)) : 50,
    cropZoom: Number.isFinite(zoom) ? Math.min(1.6, Math.max(1, zoom)) : 1,
    cropRotationDeg: Number.isFinite(rotation) ? ((Math.round(rotation / 90) * 90) % 360 + 360) % 360 : 0,
  };
}

function sanitizeDecision(decision) {
  const humanState = String(decision.humanState || "NEUTRAL").toUpperCase();
  const productionDecision =
    humanState === "APPROVE" ? "APPROVE" : humanState === "DISAPPROVE" ? "DISAPPROVE" : "";
  const crop = normalizeCropAdjustment(decision.cropAdjustment);
  return {
    bucket: decision.bucket,
    partFile: decision.partFile,
    rowKey: decision.rowKey,
    sourceFile: decision.sourceFile || "",
    sourceRowNumber: decision.sourceRowNumber || "",
    defaultDecision: decision.defaultDecision || "",
    cvDecision: decision.cvDecision || "",
    cvReasonCode: decision.cvReasonCode || "",
    cvReasonSummary: decision.cvReasonSummary || "",
    sorterRecommendation: decision.sorterRecommendation || "",
    sorterReasonCodes: decision.sorterReasonCodes || "",
    humanState,
    production_decision: productionDecision,
    rejection_reason: productionDecision === "DISAPPROVE" ? decision.rejectionReason || "" : "",
    review_notes: decision.reviewNotes || "",
    crop_has_adjustment: crop.hasCropAdjustment,
    crop_mode: crop.cropMode,
    crop_aspect_ratio: crop.cropAspectRatio,
    crop_object_position_x_pct: crop.cropObjectPositionXPct,
    crop_object_position_y_pct: crop.cropObjectPositionYPct,
    crop_zoom: crop.cropZoom,
    crop_rotation_deg: crop.cropRotationDeg,
  };
}

function groupDecisions(decisions) {
  const groups = new Map();
  for (const decision of decisions.map(sanitizeDecision)) {
    if (!decision.bucket || !decision.partFile || !decision.rowKey) continue;
    const groupKey = `${decision.bucket}::${decision.partFile}`;
    if (!groups.has(groupKey)) groups.set(groupKey, []);
    groups.get(groupKey).push(decision);
  }
  return groups;
}

async function writeReturnWorkbook(bucket, partFile, decisions, exportStamp) {
  const sourcePath = path.join(packageDir, partFile);
  if (!existsSync(sourcePath)) throw new Error(`Source workbook not found: ${partFile}`);

  const sourceWorkbook = new ExcelJS.Workbook();
  await sourceWorkbook.xlsx.readFile(sourcePath);
  const sourceSheet = sourceWorkbook.worksheets[0];
  const sourceHeaders = getHeaders(sourceSheet);
  const headers = [...sourceHeaders];
  for (const header of cropReturnHeaders) {
    if (!headers.includes(header)) headers.push(header);
  }
  const sourceRowsByKey = new Map();

  sourceSheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1) return;
    const raw = getRowObject(row, sourceHeaders);
    const rowKey =
      raw.review_row_key ||
      `${raw.source_file || "unknown"}::${raw.source_row_number || rowNumber}`;
    sourceRowsByKey.set(rowKey, { raw, rowNumber });
  });

  const returnWorkbook = new ExcelJS.Workbook();
  returnWorkbook.creator = "FWM image review dashboard";
  returnWorkbook.created = new Date();
  const sheet = returnWorkbook.addWorksheet("reviewed_rows", {
    views: [{ state: "frozen", ySplit: 1 }],
  });
  sheet.addRow(headers);
  sheet.getRow(1).font = { bold: true };

  const decisionByRowKey = new Map(decisions.map((decision) => [decision.rowKey, decision]));
  for (const decision of decisions) {
    const source = sourceRowsByKey.get(decision.rowKey);
    if (!source) continue;
    const values = headers.map((header) => {
      if (header === "production_decision") return decision.production_decision;
      if (header === "rejection_reason") return decision.rejection_reason;
      if (header === "review_notes") return decision.review_notes;
      if (header === "crop_has_adjustment") return decision.crop_has_adjustment ? "TRUE" : "";
      if (header === "crop_mode") return decision.crop_has_adjustment ? decision.crop_mode : "";
      if (header === "crop_aspect_ratio") return decision.crop_has_adjustment ? decision.crop_aspect_ratio : "";
      if (header === "crop_object_position_x_pct") return decision.crop_has_adjustment ? decision.crop_object_position_x_pct : "";
      if (header === "crop_object_position_y_pct") return decision.crop_has_adjustment ? decision.crop_object_position_y_pct : "";
      if (header === "crop_zoom") return decision.crop_has_adjustment ? decision.crop_zoom : "";
      if (header === "crop_rotation_deg") return decision.crop_has_adjustment ? decision.crop_rotation_deg : "";
      if (header === "image_preview") {
        const imageUrl = source.raw.image_url_to_use || source.raw.raw_scraped_image_url || "";
        return imageUrl ? { formula: `IF(X${sheet.rowCount + 1}<>"",IMAGE(X${sheet.rowCount + 1}),"")` } : "";
      }
      return source.raw[header] || "";
    });
    sheet.addRow(values);
  }

  const reasonsSheet = returnWorkbook.addWorksheet("rejection_reasons");
  const sourceReasonSheet = sourceWorkbook.worksheets[1];
  if (sourceReasonSheet) {
    sourceReasonSheet.eachRow((row) => {
      reasonsSheet.addRow([getCellText(row, 1)]);
    });
  }

  const partMatch = partFile.match(/part_(\d{3})/);
  const part = partMatch ? partMatch[1] : "unknown";
  const outputName = `human_labeled_${bucket}_part_${part}_${exportStamp}.xlsx`;
  const outputPath = path.join(returnsDir, outputName);
  await mkdir(returnsDir, { recursive: true });
  await returnWorkbook.xlsx.writeFile(outputPath);

  return {
    bucket,
    partFile,
    outputName,
    outputPath,
    rowCount: decisions.length,
    rowKeys: Array.from(decisionByRowKey.keys()),
  };
}

async function saveDecisions(payload) {
  const decisions = Array.isArray(payload.decisions) ? payload.decisions : [];
  if (decisions.length === 0) throw new Error("No decisions were provided.");

  const exportStamp = sanitizeTimestamp();
  const reviewedAt = new Date().toISOString();
  const groups = groupDecisions(decisions);
  const outputs = [];
  const manifest = await readManifest();

  for (const [groupKey, groupDecisionsList] of groups.entries()) {
    const [bucket, partFile] = groupKey.split("::");
    const output = await writeReturnWorkbook(bucket, partFile, groupDecisionsList, exportStamp);
    outputs.push(output);

    for (const decision of groupDecisionsList) {
      const key = getDecisionKey(bucket, partFile, decision.rowKey);
      manifest.decisions[key] = {
        bucket,
        part_file: partFile,
        review_row_key: decision.rowKey,
        source_file: decision.sourceFile,
        source_row_number: decision.sourceRowNumber,
        default_decision: decision.defaultDecision,
        cv_decision: decision.cvDecision,
        cv_reason_code: decision.cvReasonCode,
        cv_reason_summary: decision.cvReasonSummary,
        sorter_recommendation: decision.sorterRecommendation,
        sorter_reason_codes: decision.sorterReasonCodes,
        human_state: decision.humanState,
        production_decision: decision.production_decision,
        rejection_reason: decision.rejection_reason,
        review_notes: decision.review_notes,
        crop_has_adjustment: decision.crop_has_adjustment,
        crop_mode: decision.crop_mode,
        crop_aspect_ratio: decision.crop_aspect_ratio,
        crop_object_position_x_pct: decision.crop_object_position_x_pct,
        crop_object_position_y_pct: decision.crop_object_position_y_pct,
        crop_zoom: decision.crop_zoom,
        crop_rotation_deg: decision.crop_rotation_deg,
        reviewed_at: reviewedAt,
        export_stamp: exportStamp,
      };
    }
  }

  const deltaName = `human_labeled_delta_${exportStamp}.json`;

  manifest.exports.push({
    export_stamp: exportStamp,
    exported_at: reviewedAt,
    delta_name: deltaName,
    output_workbooks: outputs.map((output) => ({
      bucket: output.bucket,
      source_part_file: output.partFile,
      output_name: output.outputName,
      row_count: output.rowCount,
    })),
  });

  await writeManifest(manifest);

  await writeFile(
    path.join(returnsDir, deltaName),
    JSON.stringify({ exported_at: reviewedAt, decisions: Object.values(manifest.decisions) }, null, 2) + "\n",
    "utf8",
  );

  return {
    ok: true,
    exportStamp,
    reviewedAt,
    outputs: outputs.map((output) => ({
      bucket: output.bucket,
      partFile: output.partFile,
      outputName: output.outputName,
      rowCount: output.rowCount,
    })),
    manifestPath,
    deltaName,
    savedDecisionCount: Object.keys(manifest.decisions).length,
  };
}

function returnFilePath(filename) {
  const resolved = path.resolve(returnsDir, filename);
  if (!resolved.startsWith(path.resolve(returnsDir) + path.sep)) {
    throw new Error(`Refusing to delete file outside returns folder: ${filename}`);
  }
  return resolved;
}

async function unlinkIfExists(filename) {
  if (!filename) return false;
  const filePath = returnFilePath(filename);
  if (!existsSync(filePath)) return false;
  await unlink(filePath);
  return true;
}

async function undoLastExport() {
  const manifest = await readManifest();
  const lastExport = manifest.exports.at(-1);
  if (!lastExport) {
    return {
      ok: true,
      undone: false,
      message: "No exports to undo.",
      decisions: [],
      deletedFiles: [],
      savedDecisionCount: Object.keys(manifest.decisions).length,
    };
  }

  const exportStamp = lastExport.export_stamp;
  const deletedFiles = [];
  const filesToDelete = [
    ...(lastExport.output_workbooks || []).map((output) => output.output_name),
    lastExport.delta_name || `human_labeled_delta_${exportStamp}.json`,
  ].filter(Boolean);

  for (const filename of filesToDelete) {
    if (await unlinkIfExists(filename)) deletedFiles.push(filename);
  }

  const undoneDecisions = [];
  for (const [key, decision] of Object.entries(manifest.decisions)) {
    if (decision.export_stamp !== exportStamp) continue;
    undoneDecisions.push({
      bucket: decision.bucket,
      partFile: decision.part_file,
      rowKey: decision.review_row_key,
      sourceFile: decision.source_file || "",
      sourceRowNumber: decision.source_row_number || "",
      defaultDecision: decision.default_decision || "",
      cvDecision: decision.cv_decision || "",
      cvReasonCode: decision.cv_reason_code || "",
      cvReasonSummary: decision.cv_reason_summary || "",
      sorterRecommendation: decision.sorter_recommendation || "",
      sorterReasonCodes: decision.sorter_reason_codes || "",
      humanState: decision.human_state || "NEUTRAL",
      rejectionReason: decision.rejection_reason || "",
      reviewNotes: decision.review_notes || "",
      cropAdjustment: normalizeCropAdjustment(decision),
    });
    delete manifest.decisions[key];
  }

  manifest.exports.pop();
  await writeManifest(manifest);

  return {
    ok: true,
    undone: true,
    exportStamp,
    deletedFiles,
    decisions: undoneDecisions,
    savedDecisionCount: Object.keys(manifest.decisions).length,
  };
}

async function serveStatic(req, res, pathname) {
  const requestedPath = pathname === "/" ? "/index.html" : pathname;
  let filePath = path.normalize(path.join(publicDir, requestedPath));
  if (!filePath.startsWith(publicDir)) {
    sendError(res, "Invalid path", 400);
    return;
  }

  try {
    const content = await readFile(filePath);
    const ext = path.extname(filePath);
    res.writeHead(200, {
      "Content-Type": contentTypes[ext] || "application/octet-stream",
      "Cache-Control": "no-store, max-age=0",
    });
    res.end(content);
  } catch {
    sendError(res, "Not found", 404);
  }
}

function createImageReviewServer() {
  return createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname === "/api/parts" && req.method === "GET") {
      sendJson(res, await listParts());
      return;
    }
    if (url.pathname === "/api/rows" && req.method === "GET") {
      const bucket = url.searchParams.get("bucket") || "needs_human_review";
      const part = url.searchParams.get("part") || "001";
      sendJson(res, await readWorkbookRows(bucket, part));
      return;
    }
    if (url.pathname === "/api/save" && req.method === "POST") {
      sendJson(res, await saveDecisions(await readJsonBody(req)));
      return;
    }
    if (url.pathname === "/api/undo-last-export" && req.method === "POST") {
      sendJson(res, await undoLastExport());
      return;
    }
    await serveStatic(req, res, url.pathname);
  } catch (error) {
    sendError(res, error.message || String(error), 500);
  }
  });
}

const port = Number(process.env.PORT || 4173);
const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === __filename;

if (invokedDirectly) {
  const server = createImageReviewServer();
  server.listen(port, () => {
    console.log(`Image review dashboard running at http://localhost:${port}`);
    console.log(`Source workbooks: ${packageDir}`);
    console.log(`Return workbooks: ${returnsDir}`);
  });
}

export {
  bucketConfig,
  createImageReviewServer,
  getBucketAndPartFromFile,
  getEligibleWorksheetSummaryFast,
  isDashboardEligibleRaw,
  listParts,
  normalizeCropAdjustment,
  readWorkbookRows,
  saveDecisions,
};
