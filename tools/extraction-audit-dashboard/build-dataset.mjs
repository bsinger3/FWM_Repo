#!/usr/bin/env node
// Build the extraction-audit dataset: every APPROVED review image (plus any
// image the reviewer left a comment on) joined to its full review comment and
// the measurements we extracted, with per-comment colour-coding precomputed.
//
// Reads (read-only):
//   - the human-labeled returns manifest (decisions: APPROVE / review_notes)
//   - the CV-gated review workbooks (image url, comment, measurement columns)
//   - the checkpoint comment cache (recovers comments on column-shifted rows)
// Writes:
//   - <FWM_Data>/_reports/extraction_audit/dataset.json
//
// Usage: node tools/extraction-audit-dashboard/build-dataset.mjs

import ExcelJS from "exceljs";
import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  defaultImageReviewPackageDir,
  defaultImageReviewReturnsDir,
} from "../image-review-dashboard/paths.mjs";
import { fwmDataDir } from "../image-review-dashboard/paths.mjs";
import { analyzeComment, isCheckable, commentId } from "./lib/analyze.mjs";

const __filename = fileURLToPath(import.meta.url);
const toolDir = path.dirname(__filename);
const repoRoot = path.resolve(toolDir, "../..");
const packageDir =
  process.env.FWM_IMAGE_REVIEW_PACKAGE_DIR || defaultImageReviewPackageDir(repoRoot);
const returnsDir =
  process.env.FWM_IMAGE_REVIEW_RETURNS_DIR || defaultImageReviewReturnsDir(repoRoot);
const manifestPath = path.join(returnsDir, "human_labeled_returns_manifest.json");
const outDir = path.join(fwmDataDir(repoRoot), "_reports", "extraction_audit");
const outPath = path.join(outDir, "dataset.json");

const bucketFilePrefix = {
  approve_candidates: "supabase_image_review_approve_candidates_part_",
  needs_human_review: "supabase_image_review_needs_human_review_part_",
  disapprove_candidates: "supabase_image_review_disapprove_candidates_part_",
};

// ---- workbook cell helpers (mirrors image-review-dashboard/server.mjs) -------
function getCellText(row, columnNumber) {
  const cell = row.getCell(columnNumber);
  if (cell.value == null) return "";
  if (typeof cell.value === "object") {
    if ("text" in cell.value) return String(cell.value.text ?? "");
    if ("result" in cell.value) return String(cell.value.result ?? "");
    if ("formula" in cell.value) return "";
    if (cell.value.richText) return cell.value.richText.map((p) => p.text).join("");
    return String(cell.text ?? "");
  }
  return String(cell.value);
}
function getHeaders(sheet) {
  const headers = [];
  sheet.getRow(1).eachCell({ includeEmpty: true }, (cell, col) => {
    headers[col - 1] = String(cell.value ?? "").trim();
  });
  return headers;
}
function getRowObject(row, headers) {
  const obj = {};
  headers.forEach((h, i) => {
    if (h) obj[h] = getCellText(row, i + 1);
  });
  return obj;
}
// A "comment" that is really a local file path (column-shift artifact). The
// image-review dashboard only knew about step_1 paths; column-shifted Amazon
// rows carry step_4 paths, so match any absolute *.csv/*.xlsx path or anything
// under FWM_Data — these are never real review prose.
function looksLikeSourcePath(value) {
  const s = String(value || "").trim();
  return /^\/.+\.(csv|xlsx)$/i.test(s) || /\/FWM_Data\//i.test(s);
}

// ---- checkpoint comment cache (recovers comments on shifted rows) -----------
function parseCsvRecords(csv) {
  const records = [];
  let record = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < csv.length; i += 1) {
    const ch = csv[i];
    const next = csv[i + 1];
    if (ch === '"') {
      if (inQuotes && next === '"') {
        field += '"';
        i += 1;
      } else inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      record.push(field);
      field = "";
    } else if ((ch === "\n" || ch === "\r") && !inQuotes) {
      if (ch === "\r" && next === "\n") i += 1;
      record.push(field);
      if (record.some((v) => v !== "")) records.push(record);
      record = [];
      field = "";
    } else field += ch;
  }
  if (field || record.length) {
    record.push(field);
    records.push(record);
  }
  return records;
}
async function buildCheckpointCommentCache() {
  const dir = path.join(packageDir, "cv_gate_checkpoint_parts");
  const byRowKey = new Map();
  if (!existsSync(dir)) return byRowKey;
  const files = (await readdir(dir)).filter((f) => f.endsWith(".csv"));
  for (const file of files) {
    const records = parseCsvRecords(await readFile(path.join(dir, file), "utf8"));
    if (records.length < 2) continue;
    const headers = records[0];
    const ki = headers.indexOf("review_row_key");
    const ci = headers.indexOf("user_comment");
    if (ki === -1 || ci === -1) continue;
    for (const rec of records.slice(1)) {
      const k = rec[ki];
      const c = rec[ci];
      if (k && c && !looksLikeSourcePath(c) && !byRowKey.has(k)) byRowKey.set(k, c);
    }
  }
  return byRowKey;
}

// Run the CURRENT Python extractor over a set of unique comments so the
// dashboard always reflects the live regexes (not the workbooks' stale columns).
// Input: Map(id -> comment). Returns: Map(id -> {dashboard measurement fields}).
function batchExtract(commentsById) {
  return new Promise((resolve, reject) => {
    const script = path.join(toolDir, "extract_batch.py");
    const proc = spawn("python3", [script], { stdio: ["pipe", "pipe", "inherit"] });
    let out = "";
    proc.stdout.on("data", (chunk) => (out += chunk));
    proc.on("error", reject);
    proc.on("close", (code) => {
      if (code !== 0) return reject(new Error(`extract_batch.py exited ${code}`));
      const byId = new Map();
      for (const line of out.split("\n")) {
        if (!line.trim()) continue;
        const rec = JSON.parse(line);
        byId.set(rec.id, rec.m);
      }
      resolve(byId);
    });
    for (const [id, comment] of commentsById) {
      proc.stdin.write(JSON.stringify({ id, comment }) + "\n");
    }
    proc.stdin.end();
  });
}

async function main() {
  if (!existsSync(manifestPath)) throw new Error(`Manifest not found: ${manifestPath}`);
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const decisions = manifest.decisions || {};

  // Collect the rows we care about: APPROVE, or any review_notes left.
  // Index by (bucket, part_file) -> Map(review_row_key -> decision).
  const wanted = new Map(); // `${bucket}::${partFile}` -> Map(rowKey, decision)
  let approvedCount = 0;
  let commentedCount = 0;
  for (const d of Object.values(decisions)) {
    const approved = String(d.production_decision || "").toUpperCase() === "APPROVE";
    const commented = String(d.review_notes || "").trim() !== "";
    if (!approved && !commented) continue;
    if (approved) approvedCount += 1;
    if (commented) commentedCount += 1;
    const key = `${d.bucket}::${d.part_file}`;
    if (!wanted.has(key)) wanted.set(key, new Map());
    wanted.get(key).set(d.review_row_key, d);
  }
  console.log(
    `Manifest: ${approvedCount} approved, ${commentedCount} commented across ${wanted.size} workbook parts.`,
  );

  const checkpointComments = await buildCheckpointCommentCache();
  console.log(`Checkpoint comment cache: ${checkpointComments.size} recovered comments.`);

  // Pass 1 — collect candidate rows + their (recovered) comments.
  const candidates = [];
  let missingWorkbooks = 0;
  for (const [key, rowMap] of wanted) {
    const [bucket, partFile] = key.split("::");
    const filePath = path.join(packageDir, partFile);
    if (!existsSync(filePath)) {
      missingWorkbooks += 1;
      continue;
    }
    const wb = new ExcelJS.Workbook();
    await wb.xlsx.readFile(filePath);
    const sheet = wb.worksheets[0];
    const headers = getHeaders(sheet);
    sheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
      if (rowNumber === 1) return;
      const raw = getRowObject(row, headers);
      const rowKey =
        raw.review_row_key || `${raw.source_file || "unknown"}::${raw.source_row_number || rowNumber}`;
      const decision = rowMap.get(rowKey);
      if (!decision) return;

      // Recover the true comment for column-shifted rows (the comment column
      // holds a file path). Fall back to the checkpoint cache; if still missing,
      // the row has no auditable comment.
      let comment = raw.user_comment || "";
      if (!comment.trim() || looksLikeSourcePath(comment)) {
        comment = checkpointComments.get(rowKey) || "";
      }
      const hasNote = String(decision.review_notes || "").trim() !== "";
      if (!comment.trim() && !hasNote) return; // nothing to audit

      const oldRowId = `${bucket}::${partFile}::${rowKey}`;
      const id = commentId(comment) || `r_${oldRowId}`;
      candidates.push({
        id,
        oldRowId,
        rowKey,
        bucket,
        partFile,
        decision: decision.production_decision || "",
        reviewNote: decision.review_notes || "",
        imageUrl: raw.image_url_to_use || raw.raw_scraped_image_url || "",
        rawImageUrl: raw.raw_scraped_image_url || "",
        productUrl: raw.product_page_url_display || raw.monetized_product_url_display || "",
        brand: raw.brand || "",
        clothingType: raw.clothing_type_id || "",
        sourceSite: raw.source_site_display || raw.source_family || "",
        size: raw.size_display || "",
        comment,
      });
    });
  }

  // Pass 2 — extract with the CURRENT regexes (one parse per unique comment).
  const uniqueComments = new Map();
  for (const c of candidates) if (!uniqueComments.has(c.id)) uniqueComments.set(c.id, c.comment);
  console.log(`Extracting with live parser over ${uniqueComments.size} unique comments…`);
  const extractionById = await batchExtract(uniqueComments);

  // Pass 3 — attach extraction, colour-code, drop non-checkable rows.
  const rows = [];
  for (const c of candidates) {
    const m = extractionById.get(c.id) || {};
    const extracted = { ...m, size: c.size };
    const analysis = analyzeComment(c.comment, extracted);
    if (!isCheckable(analysis, extracted)) continue;
    rows.push({
      ...c,
      extracted,
      segments: analysis.segments,
      suspicion: analysis.suspicion,
      mentionedTypes: analysis.mentionedTypes,
    });
  }
  const read = rows.length;

  // Dedupe by comment: the same review comment recurs across many image rows,
  // and we only need to audit (and flag) each unique comment once. Keep one
  // representative per comment id — preferring a row the reviewer commented on,
  // then highest suspicion. Record how many image rows share it.
  const rowKeyToId = {}; // every original row -> comment id, for flag migration
  const groups = new Map();
  for (const r of rows) {
    rowKeyToId[r.oldRowId] = r.id;
    if (!groups.has(r.id)) groups.set(r.id, []);
    groups.get(r.id).push(r);
  }
  const deduped = [];
  for (const group of groups.values()) {
    group.sort((a, b) => (b.reviewNote ? 1 : 0) - (a.reviewNote ? 1 : 0) || b.suspicion - a.suspicion);
    const rep = group[0];
    rep.duplicateCount = group.length;
    rep.imageUrls = [...new Set(group.map((g) => g.imageUrl).filter(Boolean))].slice(0, 8);
    const notes = [...new Set(group.map((g) => g.reviewNote).filter(Boolean))];
    rep.reviewNote = notes.join("  |  ");
    delete rep.oldRowId;
    deduped.push(rep);
  }

  // Mismatch-first: rows the reviewer commented on first, then highest suspicion.
  deduped.sort((a, b) => {
    const ac = a.reviewNote ? 1 : 0;
    const bc = b.reviewNote ? 1 : 0;
    if (ac !== bc) return bc - ac;
    return b.suspicion - a.suspicion;
  });

  await mkdir(outDir, { recursive: true });
  const payload = {
    built_at: new Date().toISOString(),
    package_dir: packageDir,
    counts: {
      approved: approvedCount,
      commented: commentedCount,
      checkable_rows: deduped.length,
      duplicate_rows_collapsed: rows.length - deduped.length,
      missing_workbooks: missingWorkbooks,
    },
    rows: deduped,
  };
  await writeFile(outPath, JSON.stringify(payload));
  await writeFile(path.join(outDir, "rowkey_to_id.json"), JSON.stringify(rowKeyToId));
  console.log(
    `Wrote ${deduped.length} unique comments (from ${rows.length} checkable rows, ${read} matched) to ${outPath}` +
      (missingWorkbooks ? ` [${missingWorkbooks} workbook parts missing on disk]` : ""),
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
