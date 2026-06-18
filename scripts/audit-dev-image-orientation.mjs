#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevSupabase,
  callSupabaseRest,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const limit = Math.max(1, Number(parseArg("limit", "100")) || 100);
const timeoutMs = Math.max(1000, Number(parseArg("timeout-ms", "10000")) || 10000);
const onlyUnchecked = !process.argv.includes("--include-checked");
const verifiedReportPath = parseArg("verified-report");
const ORIENTATION_MODEL_VERSION = "image_orientation_exif_dimensions_v1";

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function parseCropSpec(value) {
  if (!value) return null;
  if (typeof value === "object") return value;
  if (typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return null;
    }
  }
  return null;
}

function displayImageUrl(row) {
  return row.original_url_display || "";
}

async function fetchCandidateRows(guard) {
  const searchParams = {
    select: "id,original_url_display,crop_spec,image_orientation_degrees,image_orientation_checked_at",
    original_url_display: "not.is.null",
    limit: String(limit),
  };
  if (onlyUnchecked) searchParams.image_orientation_checked_at = "is.null";
  const { data } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "images",
    method: "GET",
    searchParams,
  });
  return Array.isArray(data) ? data : [];
}

async function fetchImagePrefix(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      redirect: "follow",
      headers: {
        "User-Agent": "FWMDevImageOrientationAudit/0.1 (+https://friendswithmeasurements.com)",
        "Range": "bytes=0-1048575",
      },
    });
    const arrayBuffer = await response.arrayBuffer();
    return {
      ok: response.ok || response.status === 206,
      status: response.status,
      content_type: response.headers.get("content-type") || "",
      final_url: response.url || url,
      bytes: Buffer.from(arrayBuffer),
    };
  } finally {
    clearTimeout(timer);
  }
}

function readUInt16(buffer, offset, littleEndian) {
  return littleEndian ? buffer.readUInt16LE(offset) : buffer.readUInt16BE(offset);
}

function readUInt32(buffer, offset, littleEndian) {
  return littleEndian ? buffer.readUInt32LE(offset) : buffer.readUInt32BE(offset);
}

function parseExifOrientationFromTiff(buffer, tiffOffset) {
  if (tiffOffset + 8 > buffer.length) return null;
  const endian = buffer.toString("ascii", tiffOffset, tiffOffset + 2);
  const littleEndian = endian === "II";
  if (!littleEndian && endian !== "MM") return null;
  if (readUInt16(buffer, tiffOffset + 2, littleEndian) !== 42) return null;
  const ifdOffset = readUInt32(buffer, tiffOffset + 4, littleEndian);
  const entryCountOffset = tiffOffset + ifdOffset;
  if (entryCountOffset + 2 > buffer.length) return null;
  const entryCount = readUInt16(buffer, entryCountOffset, littleEndian);
  for (let i = 0; i < entryCount; i += 1) {
    const entryOffset = entryCountOffset + 2 + i * 12;
    if (entryOffset + 12 > buffer.length) break;
    const tag = readUInt16(buffer, entryOffset, littleEndian);
    if (tag !== 0x0112) continue;
    return readUInt16(buffer, entryOffset + 8, littleEndian);
  }
  return null;
}

function parseJpegMetadata(buffer) {
  if (buffer.length < 4 || buffer[0] !== 0xff || buffer[1] !== 0xd8) return {};
  const sofMarkers = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);
  let offset = 2;
  const metadata = { format: "jpeg", width: null, height: null, exif_orientation: null };
  while (offset + 4 <= buffer.length) {
    if (buffer[offset] !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = buffer[offset + 1];
    offset += 2;
    if (marker === 0xda || marker === 0xd9) break;
    if (offset + 2 > buffer.length) break;
    const segmentLength = buffer.readUInt16BE(offset);
    const segmentStart = offset + 2;
    const segmentEnd = offset + segmentLength;
    if (segmentEnd > buffer.length) break;
    if (marker === 0xe1 && buffer.toString("ascii", segmentStart, segmentStart + 6) === "Exif\0\0") {
      metadata.exif_orientation = parseExifOrientationFromTiff(buffer, segmentStart + 6);
    }
    if (sofMarkers.has(marker) && segmentStart + 7 <= buffer.length) {
      metadata.height = buffer.readUInt16BE(segmentStart + 1);
      metadata.width = buffer.readUInt16BE(segmentStart + 3);
    }
    offset = segmentEnd;
  }
  return metadata;
}

function parsePngMetadata(buffer) {
  const signature = "89504e470d0a1a0a";
  if (buffer.length < 24 || buffer.subarray(0, 8).toString("hex") !== signature) return {};
  if (buffer.toString("ascii", 12, 16) !== "IHDR") return {};
  return {
    format: "png",
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
    exif_orientation: null,
  };
}

function parseImageMetadata(buffer, contentType) {
  const lowerType = String(contentType || "").toLowerCase();
  if (lowerType.includes("png") || buffer.subarray(0, 8).toString("hex") === "89504e470d0a1a0a") return parsePngMetadata(buffer);
  return parseJpegMetadata(buffer);
}

function rotationFromExif(orientation) {
  // EXIF values involving mirroring are reduced to the display rotation component.
  if (orientation === 3) return 180;
  if (orientation === 6) return 90;
  if (orientation === 8) return 270;
  return 0;
}

function proposeOrientation({ metadata, cropSpec }) {
  const existingRotation = Number(cropSpec?.rotationDeg ?? cropSpec?.rotation_deg ?? 0);
  const allowedExisting = [0, 90, 180, 270].includes(existingRotation) ? existingRotation : 0;
  const exifRotation = rotationFromExif(metadata.exif_orientation);
  if (exifRotation && allowedExisting !== exifRotation) {
    return {
      proposed_rotation_deg: exifRotation,
      confidence: "high",
      evidence: {
        reason: "exif_orientation_requires_rotation",
        exif_orientation: metadata.exif_orientation,
        existing_rotation_deg: allowedExisting,
        width: metadata.width ?? null,
        height: metadata.height ?? null,
      },
    };
  }
  return {
    proposed_rotation_deg: allowedExisting,
    confidence: "low",
    evidence: {
      reason: "no_high_confidence_rotation_signal",
      exif_orientation: metadata.exif_orientation ?? null,
      existing_rotation_deg: allowedExisting,
      width: metadata.width ?? null,
      height: metadata.height ?? null,
    },
  };
}

async function auditOne(row) {
  const url = displayImageUrl(row);
  const cropSpec = parseCropSpec(row.crop_spec);
  const base = {
    image_id: row.id,
    image_url: url,
    current_crop_spec: cropSpec,
    current_image_orientation_degrees: row.image_orientation_degrees,
    current_image_orientation_checked_at: row.image_orientation_checked_at,
  };
  if (!url) return { ...base, skipped: true, skip_reason: "missing_image_url" };
  try {
    const fetched = await fetchImagePrefix(url);
    if (!fetched.ok) {
      return { ...base, skipped: true, skip_reason: `http_${fetched.status}`, http_status: fetched.status, final_url: fetched.final_url };
    }
    const metadata = parseImageMetadata(fetched.bytes, fetched.content_type);
    const proposed = proposeOrientation({ metadata, cropSpec });
    return {
      ...base,
      skipped: false,
      http_status: fetched.status,
      content_type: fetched.content_type,
      final_url: fetched.final_url,
      dimensions: {
        width: metadata.width ?? null,
        height: metadata.height ?? null,
        format: metadata.format ?? null,
      },
      exif_orientation: metadata.exif_orientation ?? null,
      proposed,
      proposed_database_write:
        proposed.proposed_rotation_deg !== Number(cropSpec?.rotationDeg ?? cropSpec?.rotation_deg ?? 0)
          ? {
              crop_spec_rotationDeg: proposed.proposed_rotation_deg,
              image_orientation_degrees: proposed.proposed_rotation_deg,
              image_orientation_confidence: proposed.confidence,
              image_orientation_model_version: ORIENTATION_MODEL_VERSION,
            }
          : null,
    };
  } catch (error) {
    return {
      ...base,
      skipped: true,
      skip_reason: error?.name === "AbortError" ? "timeout" : "fetch_error",
      error: String(error?.message || error),
    };
  }
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

async function applyUpdates(guard, results) {
  const updates = results.filter((result) => result.proposed_database_write && result.proposed?.confidence === "high");
  for (const result of updates) {
    const rotationDeg = result.proposed.proposed_rotation_deg;
    await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "images",
      method: "PATCH",
      searchParams: { id: `eq.${result.image_id}` },
      body: {
        crop_spec: mergeCropSpecWithRotation(result.current_crop_spec, rotationDeg),
        image_orientation_degrees: rotationDeg,
        image_orientation_confidence: result.proposed.confidence,
        image_orientation_evidence: result.proposed.evidence,
        image_orientation_checked_at: new Date().toISOString(),
        image_orientation_model_version: ORIENTATION_MODEL_VERSION,
      },
      prefer: "return=minimal",
    });
  }
  return updates.length;
}

function summarize(results) {
  const summary = {
    scanned: results.length,
    skipped: results.filter((result) => result.skipped).length,
    proposed_nonzero_rotations: results.filter((result) => result.proposed?.proposed_rotation_deg && result.proposed.proposed_rotation_deg !== 0).length,
    proposed_writes: results.filter((result) => result.proposed_database_write).length,
    high_confidence_writes: results.filter((result) => result.proposed_database_write && result.proposed?.confidence === "high").length,
  };
  return summary;
}

async function requirePassedVerificationReport(expectedType) {
  if (!verifiedReportPath) {
    throw new Error(`Apply mode requires --verified-report=/absolute/path/dev_refresh_report_verify_${expectedType}_*.json from a passed report verification.`);
  }
  const report = JSON.parse(await readFile(path.resolve(verifiedReportPath), "utf8"));
  if (report.report_type !== expectedType || report.passed !== true) {
    throw new Error(`Verification report did not pass for ${expectedType}: ${verifiedReportPath}`);
  }
  return report;
}

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function rotatedImageStyle(rotationDeg) {
  const rotation = [0, 90, 180, 270].includes(Number(rotationDeg)) ? Number(rotationDeg) : 0;
  const scale = rotation === 90 || rotation === 270 ? 4 / 3 : 1;
  return `transform: scale(${scale}) rotate(${rotation}deg);`;
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function orientationReviewRows(results) {
  return (results || [])
    .filter((result) => result.skipped || result.proposed_database_write)
    .map((result) => ({
      image_id: result.image_id,
      image_url: result.image_url,
      review_reason: result.skipped ? result.skip_reason || "audit_skipped" : "proposed_rotation_write",
      current_rotation_deg: Number(result.current_crop_spec?.rotationDeg ?? result.current_crop_spec?.rotation_deg ?? 0) || 0,
      proposed_rotation_deg: result.proposed?.proposed_rotation_deg ?? "",
      confidence: result.proposed?.confidence || "",
      width: result.dimensions?.width ?? "",
      height: result.dimensions?.height ?? "",
      format: result.dimensions?.format ?? "",
      exif_orientation: result.exif_orientation ?? "",
      evidence_json: JSON.stringify(result.proposed?.evidence || {}),
      final_url: result.final_url || "",
    }));
}

function buildOrientationReviewCsv(rows) {
  const headers = [
    "image_id",
    "image_url",
    "review_reason",
    "current_rotation_deg",
    "proposed_rotation_deg",
    "confidence",
    "width",
    "height",
    "format",
    "exif_orientation",
    "evidence_json",
    "final_url",
  ];
  return [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n") + "\n";
}

function buildReviewHtml(report) {
  const cards = report.results
    .map((result) => {
      const proposed = result.proposed?.proposed_rotation_deg ?? 0;
      const currentRotation = Number(result.current_crop_spec?.rotationDeg ?? result.current_crop_spec?.rotation_deg ?? 0) || 0;
      return `
        <article class="card">
          <h2>${htmlEscape(result.image_id)}</h2>
          <p><a href="${htmlEscape(result.image_url)}" target="_blank" rel="noreferrer">source image</a></p>
          <div class="frames">
            <figure>
              <div class="frame"><img src="${htmlEscape(result.image_url)}" style="${rotatedImageStyle(currentRotation)}" loading="lazy"></div>
              <figcaption>Current ${htmlEscape(currentRotation)} deg</figcaption>
            </figure>
            <figure>
              <div class="frame"><img src="${htmlEscape(result.image_url)}" style="${rotatedImageStyle(proposed)}" loading="lazy"></div>
              <figcaption>Proposed ${htmlEscape(proposed)} deg</figcaption>
            </figure>
          </div>
          <pre>${htmlEscape(JSON.stringify({
            skipped: result.skipped,
            skip_reason: result.skip_reason,
            dimensions: result.dimensions,
            exif_orientation: result.exif_orientation,
            proposed: result.proposed,
            proposed_database_write: result.proposed_database_write,
          }, null, 2))}</pre>
        </article>`;
    })
    .join("\n");
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FWM Dev Image Orientation Audit</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; color: #1f2933; }
    header { margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
    .card { border: 1px solid #d9e2ec; border-radius: 8px; padding: 12px; background: #fff; }
    h2 { font-size: 13px; overflow-wrap: anywhere; }
    .frames { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .frame { aspect-ratio: 3 / 4; overflow: hidden; background: #f0f4f8; display: flex; align-items: center; justify-content: center; }
    img { width: 100%; height: 100%; object-fit: cover; transform-origin: center center; }
    figcaption { font-size: 12px; color: #52606d; margin-top: 4px; }
    pre { white-space: pre-wrap; font-size: 11px; background: #f8fafc; padding: 8px; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <header>
    <h1>FWM Dev Image Orientation Audit</h1>
    <p>Generated ${htmlEscape(report.generated_at)}. Mode: ${htmlEscape(report.mode)}. Rows scanned: ${htmlEscape(report.summary.scanned)}. Proposed writes: ${htmlEscape(report.summary.proposed_writes)}.</p>
  </header>
  <main class="grid">${cards}</main>
</body>
</html>
`;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Image orientation audit guard" });
  if (apply) {
    throw new Error("Direct orientation audit apply is disabled. Run a dry-run audit, verify it, then use npm run dev-images:orientation:promote with the exact report.");
  }

  const rows = await fetchCandidateRows(guard);
  const results = [];
  for (const row of rows) results.push(await auditOne(row));

  let appliedRows = 0;
  if (apply) {
    requireExplicitWriteFlag();
    await requirePassedVerificationReport("orientation");
    appliedRows = await applyUpdates(guard, results);
  }

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportStem = `dev_image_orientation_audit_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const reportPath = path.join(reportsDir, `${reportStem}.json`);
  const reviewHtmlPath = path.join(reportsDir, `${reportStem}.html`);
  const reviewCsvPath = path.join(reportsDir, `${reportStem}_review.csv`);
  const summary = summarize(results);
  const reviewRows = orientationReviewRows(results);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    orientation_model_version: ORIENTATION_MODEL_VERSION,
    limit,
    only_unchecked: onlyUnchecked,
    timeout_ms: timeoutMs,
    summary,
    applied_rows: appliedRows,
    review_html_path: reviewHtmlPath,
    review_csv_path: reviewCsvPath,
    review_csv_row_count: reviewRows.length,
    results,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(reviewHtmlPath, buildReviewHtml(report), "utf8");
  await writeFile(reviewCsvPath, buildOrientationReviewCsv(reviewRows), "utf8");
  console.log(`Wrote image orientation audit report: ${reportPath}`);
  console.log(`Wrote image orientation review HTML: ${reviewHtmlPath}`);
  console.log(`Wrote image orientation review CSV: ${reviewCsvPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Rows scanned: ${summary.scanned}`);
  console.log(`Review CSV rows: ${reviewRows.length}`);
  console.log(`Proposed writes: ${summary.proposed_writes}`);
  console.log(`High-confidence writes: ${summary.high_confidence_writes}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
