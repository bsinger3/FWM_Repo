import ExcelJS from "exceljs";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile, unlink } from "node:fs/promises";
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

function getBucketAndPartFromFile(filename) {
  for (const [bucket, config] of Object.entries(bucketConfig)) {
    const match = filename.match(config.pattern);
    if (match) {
      return { bucket, partNumber: Number(match[1]), part: match[1] };
    }
  }
  return null;
}

async function listParts() {
  const { readdir } = await import("node:fs/promises");
  const files = await readdir(packageDir);
  const buckets = Object.fromEntries(
    Object.entries(bucketConfig).map(([bucket, config]) => [
      bucket,
      {
        bucket,
        label: config.label,
        defaultDecision: config.defaultDecision,
        parts: [],
      },
    ]),
  );

  for (const filename of files) {
    const parsed = getBucketAndPartFromFile(filename);
    if (!parsed) continue;
    buckets[parsed.bucket].parts.push({
      part: parsed.part,
      partNumber: parsed.partNumber,
      filename,
    });
  }

  for (const bucket of Object.values(buckets)) {
    bucket.parts.sort((a, b) => a.partNumber - b.partNumber);
  }

  const manifest = await readManifest();
  const savedCountsByBucket = {};
  const savedCountsByExport = {};
  for (const decision of Object.values(manifest.decisions)) {
    savedCountsByBucket[decision.bucket] = (savedCountsByBucket[decision.bucket] || 0) + 1;
    if (decision.export_stamp) {
      savedCountsByExport[decision.export_stamp] = (savedCountsByExport[decision.export_stamp] || 0) + 1;
    }
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

function mapHumanState(productionDecision) {
  const normalized = String(productionDecision || "").trim().toUpperCase();
  if (["APPROVE", "APPROVED", "YES"].includes(normalized)) return "APPROVE";
  if (["DISAPPROVE", "REJECT", "REJECTED", "NO"].includes(normalized)) return "DISAPPROVE";
  return "NEUTRAL";
}

function normalizeDisplayRow(raw, bucket, part, partFile, defaultDecision, savedDecision) {
  const rowKey =
    raw.review_row_key ||
    `${raw.source_file || "unknown"}::${raw.source_row_number || raw.__rowNumber}`;
  const productionDecision = savedDecision?.production_decision ?? raw.production_decision ?? "";
  const rejectionReason = savedDecision?.rejection_reason ?? raw.rejection_reason ?? "";
  const reviewNotes = savedDecision?.review_notes ?? raw.review_notes ?? "";
  const humanState = savedDecision ? mapHumanState(productionDecision) : "NEUTRAL";

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
      userComment: raw.user_comment || "",
      productTitle: raw.product_title_raw || "",
      productCategory: raw.product_category_raw || "",
    },
    source: {
      sourceFamily: raw.source_family || "",
      sourceSite: raw.source_site_display || "",
      sourceFile: raw.source_file || "",
      sourceRowNumber: raw.source_row_number || "",
    },
  };
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
  const rows = [];

  sheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1) return;
    const raw = getRowObject(row, headers);
    raw.__rowNumber = rowNumber;
    const rowKey =
      raw.review_row_key ||
      `${raw.source_file || "unknown"}::${raw.source_row_number || rowNumber}`;
    const decisionKey = getDecisionKey(bucket, filename, rowKey);
    const savedDecision = manifest.decisions[decisionKey];
    rows.push(
      normalizeDisplayRow(raw, bucket, partString, filename, config.defaultDecision, savedDecision),
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

function sanitizeDecision(decision) {
  const humanState = String(decision.humanState || "NEUTRAL").toUpperCase();
  const productionDecision =
    humanState === "APPROVE" ? "APPROVE" : humanState === "DISAPPROVE" ? "DISAPPROVE" : "";
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
  };
}

function groupDecisions(decisions) {
  const groups = new Map();
  for (const decision of decisions.map(sanitizeDecision)) {
    if (!decision.bucket || !decision.partFile || !decision.rowKey) continue;
    if (decision.humanState === "DISAPPROVE" && !decision.rejection_reason) {
      throw new Error(`Rejected row is missing a rejection reason: ${decision.rowKey}`);
    }
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
  const headers = getHeaders(sourceSheet);
  const sourceRowsByKey = new Map();

  sourceSheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1) return;
    const raw = getRowObject(row, headers);
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
    res.writeHead(200, { "Content-Type": contentTypes[ext] || "application/octet-stream" });
    res.end(content);
  } catch {
    sendError(res, "Not found", 404);
  }
}

const server = createServer(async (req, res) => {
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

const port = Number(process.env.PORT || 4173);
server.listen(port, () => {
  console.log(`Image review dashboard running at http://localhost:${port}`);
  console.log(`Source workbooks: ${packageDir}`);
  console.log(`Return workbooks: ${returnsDir}`);
});
