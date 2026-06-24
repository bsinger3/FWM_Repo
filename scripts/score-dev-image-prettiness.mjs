#!/usr/bin/env node

// Prettiness / photo-quality scorer (plan section 12), Phase 0 + body signals.
//
// Deterministic, no-ML pass. Components:
//   - aspect / resolution: from fetched image dimensions (JPEG/PNG/WebP headers).
//   - body_visible: how complete the person's body is in the SOURCE image, from
//     the workbook YOLO/pose CV metrics joined by review_row_key.
//   - body_card_coverage: how much of the body survives the 3:4 card crop and how
//     much of the card it fills AFTER cropping (crop-aware; uses crop_spec when
//     present, else a centered cover crop). This is what auto-cropping will tune.
// Aesthetic (CLIP, Phase 1) and technical (MUSIQ/NIMA, Phase 2) stay null.
//
// DRY-RUN ONLY: never writes Supabase rows. Writes a score-distribution JSON,
// an HTML review sheet (top/middle/bottom buckets), and a CSV.

import { mkdir, writeFile, readFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { assertApprovedDevSupabase, callSupabaseRest, printGuardSummary } from "./lib/dev-supabase-guard.mjs";
import { loadWorkbookCvIndex } from "./lib/workbook-cv-index.mjs";
import { loadKeypointIndex, analyzeKeypoints } from "./lib/keypoint-index.mjs";
import { estimateBodyAfterCrop, estimateBestAchievableCrop, cropWindowFractions } from "./lib/card-crop-geometry.mjs";
import { computePixelStats } from "./lib/pixel-stats.mjs";
import {
  LIGHTING_WEIGHTS,
  exposureScore,
  brightnessScore,
  contrastScore,
  castScore,
  lightingScore,
} from "./lib/lighting-score.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const limit = Math.max(1, Number(parseArg("limit", "200")) || 200);
const timeoutMs = Math.max(1000, Number(parseArg("timeout-ms", "10000")) || 10000);
const reviewBucketSize = Math.max(1, Number(parseArg("review-bucket", "30")) || 30);
const rebuildCvCache = process.argv.includes("--rebuild-cv-cache");
const rebuildKpCache = process.argv.includes("--rebuild-kp-cache");
const sourceFilter = parseArg("source", "all"); // all | workbook | baseline
// Pixel decode (lighting + clutter) is on by default; --no-pixels reverts to the
// v2 header-only domain-fit pass.
const pixelsEnabled = !process.argv.includes("--no-pixels");
// Score the post-autocrop CARD instead of the full source: load id->crop_spec
// from a crop-backfill report and apply each window to the pixels before lighting
// /clutter. --only-auto-crops restricts the run to rows that have an autocrop;
// --compare-card also measures the full source so the delta is visible.
const autoCropsPath = parseArg("auto-crops", null);
const onlyAutoCrops = process.argv.includes("--only-auto-crops");
const compareCard = process.argv.includes("--compare-card");
const PRETTINESS_MODEL_VERSION = pixelsEnabled ? "prettiness_domainfit_technical_v5" : "prettiness_domain_fit_v2";

// Plan target blend. Aesthetic (CLIP) is still deferred; v3 fills the technical
// bucket with a deterministic lighting + coarse-clutter proxy. Null components
// are skipped, but technical's share is CLAMPED while aesthetic is absent (see
// blendPrettiness) so a half-finished proxy can't dominate the trusted domain-fit
// signal.
const PLAN_BLEND = { aesthetic: 0.55, technical: 0.25, domain_fit: 0.2 };
// While aesthetic is null, technical keeps at most its planned 25% share and the
// trusted domain-fit signal absorbs the orphaned aesthetic weight (-> 75%),
// instead of renormalization handing technical 56%.
const TECHNICAL_INTERIM_CAP = 0.25;
// Sub-weights inside the domain-fit component (sum to 1). Body-centric because
// fit-shopping usefulness is the point; null components are skipped + renormalized.
// body_visible is keypoint-aware (head/feet must survive the card crop);
// composition rewards a centered subject with the head/feet in frame; face_visible
// (from YuNet) rewards a visible face — all "is this a nice photo of the person".
const DOMAIN_FIT_WEIGHTS = {
  aspect: 0.12,
  resolution: 0.08,
  body_visible: 0.28,
  body_card_coverage: 0.27,
  composition: 0.1,
  face_visible: 0.15,
};
// Sub-weights inside the technical-quality component. Lighting is trustworthy;
// colorfulness rewards vivid frames; clutter is a coarse whole-frame proxy, so it
// is weighted lowest.
const TECHNICAL_WEIGHTS = { lighting: 0.45, colorfulness: 0.25, clutter: 0.3 };
// Lighting sub-scoring (exposure/brightness/contrast/cast) lives in
// ./lib/lighting-score.mjs so the calibration dashboard shares the exact logic;
// LIGHTING_WEIGHTS is re-exported from there and imported above.

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function clamp01(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

function round(value, digits = 4) {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
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

// Build id -> auto crop_spec from a crop-backfill report (planned_writes wins over
// sample_writes). These are the taxonomy-aware autocrop windows not yet written
// to the DB, so we can score the card they would produce.
async function loadAutoCropMap(reportPath) {
  const report = JSON.parse(await readFile(reportPath, "utf8"));
  const map = new Map();
  for (const key of ["sample_writes", "planned_writes"]) {
    for (const row of Array.isArray(report[key]) ? report[key] : []) {
      const id = row.id || row.image_id;
      const spec = row.crop_spec || row.cropSpec;
      if (id && spec) map.set(String(id), spec);
    }
  }
  return { map, model: report.crop_model_version || null };
}

async function fetchCandidateRows(guard, restrictIds = null) {
  const searchParams = {
    select:
      "id,original_url_display,crop_spec,full_body_visible,review_row_key,source_file,prettiness_score,prettiness_scored_at",
    original_url_display: "not.is.null",
    order: "id",
    limit: String(limit),
  };
  if (restrictIds && restrictIds.length) {
    searchParams.id = `in.(${restrictIds.join(",")})`;
  } else if (sourceFilter === "workbook") searchParams.source_file = "neq.production_baseline_pg_dump";
  else if (sourceFilter === "baseline") searchParams.source_file = "eq.production_baseline_pg_dump";
  const { data } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "images",
    method: "GET",
    searchParams,
  });
  return Array.isArray(data) ? data : [];
}

// full=false fetches only the first 1MB (enough for dimension headers); full=true
// downloads the whole image so it can be decoded for pixel stats.
async function fetchImagePrefix(url, { full = false } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = {
      "User-Agent": "FWMDevPrettinessScorer/0.3 (+https://friendswithmeasurements.com)",
    };
    if (!full) headers.Range = "bytes=0-1048575";
    const response = await fetch(url, {
      signal: controller.signal,
      redirect: "follow",
      headers,
    });
    const arrayBuffer = await response.arrayBuffer();
    return {
      ok: response.ok || response.status === 206,
      status: response.status,
      content_type: response.headers.get("content-type") || "",
      bytes: Buffer.from(arrayBuffer),
    };
  } finally {
    clearTimeout(timer);
  }
}

function parseJpegMetadata(buffer) {
  if (buffer.length < 4 || buffer[0] !== 0xff || buffer[1] !== 0xd8) return {};
  const sofMarkers = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);
  let offset = 2;
  const metadata = { format: "jpeg", width: null, height: null };
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
  return { format: "png", width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function parseWebpMetadata(buffer) {
  if (buffer.length < 30) return {};
  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WEBP") return {};
  const fourcc = buffer.toString("ascii", 12, 16);
  const meta = { format: "webp", width: null, height: null };
  if (fourcc === "VP8 ") {
    // Lossy: 14-bit dimensions at byte 26 (width) and 28 (height).
    meta.width = buffer.readUInt16LE(26) & 0x3fff;
    meta.height = buffer.readUInt16LE(28) & 0x3fff;
  } else if (fourcc === "VP8L") {
    // Lossless: 14-bit dimensions packed after the 0x2f signature byte.
    const bits = buffer.readUInt32LE(21);
    meta.width = (bits & 0x3fff) + 1;
    meta.height = ((bits >> 14) & 0x3fff) + 1;
  } else if (fourcc === "VP8X") {
    // Extended: 24-bit canvas dimensions minus one at byte 24/27.
    meta.width = (buffer[24] | (buffer[25] << 8) | (buffer[26] << 16)) + 1;
    meta.height = (buffer[27] | (buffer[28] << 8) | (buffer[29] << 16)) + 1;
  }
  return meta;
}

function parseImageMetadata(buffer, contentType) {
  const lowerType = String(contentType || "").toLowerCase();
  if (buffer.subarray(0, 4).toString("ascii") === "RIFF" && buffer.subarray(8, 12).toString("ascii") === "WEBP") {
    return parseWebpMetadata(buffer);
  }
  if (lowerType.includes("png") || buffer.subarray(0, 8).toString("hex") === "89504e470d0a1a0a") {
    return parsePngMetadata(buffer);
  }
  if (lowerType.includes("webp")) return parseWebpMetadata(buffer);
  return parseJpegMetadata(buffer);
}

// --- Component scorers (each returns 0..1, or null when the signal is absent) ---

// Reward a portrait frame that fills a 3:4 card; penalize landscape and extremes.
function aspectScore(width, height) {
  if (!width || !height) return null;
  const ratio = height / width; // > 1 is portrait
  if (ratio >= 1.2 && ratio <= 1.5) return 1; // near the 3:4 (1.333) sweet spot
  if (ratio >= 1.0 && ratio < 1.2) return 0.85; // squareish portrait, still fine
  if (ratio > 1.5 && ratio <= 2.0) return 0.7; // tall portrait, croppable
  if (ratio > 2.0) return 0.4; // very tall / banner-like
  if (ratio >= 0.85 && ratio < 1.0) return 0.55; // squareish landscape
  if (ratio >= 0.6 && ratio < 0.85) return 0.35; // landscape
  return 0.15; // very wide landscape
}

// Reward enough resolution to crop into a card cleanly.
function resolutionScore(width, height) {
  if (!width || !height) return null;
  const minDim = Math.min(width, height);
  if (minDim >= 800) return 1;
  if (minDim >= 500) return 0.8;
  if (minDim >= 350) return 0.6;
  if (minDim >= 200) return 0.35;
  return 0.15;
}

// How well the person's body is shown in the DISPLAYED frame. Base completeness is
// the pose-coverage score; when per-joint keypoints are available we additionally
// require the head (nose) and feet (ankles) to actually be IN the card window —
// the aggregate pose score alone happily rates a headless or head-cropped body ~0.9,
// which is the bug this fixes. Missing head is penalized hard, missing feet mildly.
function bodyVisibleScore(cv, kpa) {
  let base = null;
  if (cv && cv.person_count !== null && cv.person_count !== 0 && cv.body_coverage_pose !== null) {
    base = clamp01(cv.body_coverage_pose);
    if (cv.person_count > 1) base *= 0.7;
  }
  if (!kpa) return base; // no keypoints: fall back to source pose coverage
  let factor = 1;
  if (!kpa.head_in_frame) factor *= 0.4; // head cut off / absent in the card -> big hit
  if (!kpa.feet_in_frame) factor *= 0.8; // feet cut -> mild (many fine shots crop at the knee)
  return clamp01((base === null ? 1 : base) * factor);
}

// Composition: reward a centered subject whose head and feet are inside the frame
// with sensible headroom. Keypoint-only (null without pose keypoints).
function compositionScore(kpa) {
  if (!kpa) return null;
  const parts = [];
  // Horizontal centering of the torso.
  if (kpa.subject_cx !== null && kpa.subject_cx !== undefined) {
    parts.push([clamp01(1 - Math.abs(kpa.subject_cx - 0.5) / 0.35), 0.4]);
  }
  // Head + feet in frame (not cut off).
  parts.push([kpa.head_in_frame ? 1 : 0, 0.3]);
  parts.push([kpa.feet_in_frame ? 1 : kpa.head_in_frame ? 0.6 : 0, 0.15]);
  // Headroom: head not jammed at the very top, not floating with too much space above.
  if (kpa.headroom !== null && kpa.headroom !== undefined) {
    const hr = kpa.headroom; // nose y in 0..1 card space
    const head =
      hr < 0.02 ? 0.2 : hr <= 0.18 ? 1 : hr <= 0.32 ? 0.7 : 0.4;
    parts.push([head, 0.15]);
  }
  return weightedMean(parts);
}

// Reward the body filling a healthy share of the card without being cut off.
function coverageSweet(coverage) {
  if (coverage <= 0.05) return 0;
  if (coverage < 0.3) return (coverage - 0.05) / 0.25;
  if (coverage <= 0.78) return 1;
  if (coverage < 1.0) return 1 - ((coverage - 0.78) / (1.0 - 0.78)) * 0.6;
  return 0.4;
}

// Crop-aware: combines how much of the body survives the crop (retention) with
// how well it fills the card (coverage sweet spot). Retention gates multiplicatively
// so a half-cut body can't score well no matter how much card it fills.
function bodyCardCoverageScore(geom) {
  if (!geom) return null;
  const retention = 0.7 * geom.retainedHeight + 0.3 * geom.retainedWidth;
  return clamp01(coverageSweet(geom.cardCoverage) * retention);
}

// --- Technical-quality scorers (lighting + coarse clutter), from pixel stats ---
// Lighting sub-scorers (exposure/brightness/contrast/cast) and lightingScore are
// imported from ./lib/lighting-score.mjs (shared with the calibration dashboard).

// Reward a visible face (YuNet). face_conf is the detector's presence strength;
// any detected face gets solid credit (floored), graded mildly by confidence.
// has_face === false means a face was looked for and not found.
function faceVisibleScore(cv) {
  if (!cv || cv.has_face === null || cv.has_face === undefined) return null;
  if (cv.has_face === false) return 0;
  const conf = Number.isFinite(cv.face_conf) ? cv.face_conf : null;
  return conf === null ? 0.8 : clamp01(0.6 + 0.4 * conf);
}

// Reward a colorful frame (Hasler-Susstrunk colorfulness from pixel stats).
// Anchors: <= DULL reads as flat/muted -> 0; >= VIVID reads as fully colorful
// -> 1. Calibrated to typical 96px-thumb colorfulness (most frames 15..75).
const COLORFULNESS_DULL = 12; // grayscale-ish / very muted
const COLORFULNESS_VIVID = 60; // richly colorful
function colorfulnessScore(stats) {
  if (!stats || !Number.isFinite(stats.colorfulness)) return null;
  return clamp01((stats.colorfulness - COLORFULNESS_DULL) / (COLORFULNESS_VIVID - COLORFULNESS_DULL));
}

// COARSE: whole-frame edge busyness as a clutter proxy. Low busyness -> clean
// frame -> high score. Conflates busy outfit/pattern with busy background until
// CV is re-run with a person mask. Anchors calibrated to the dev workbook
// population (50-image sample 2026-06-22: busyness p10≈0.40 … p90≈0.66, on a
// 96px thumbnail). May need revisiting on a larger/different image set.
const CLUTTER_BUSYNESS_CLEAN = 0.4; // <= this reads as a clean frame -> 1.0
const CLUTTER_BUSYNESS_BUSY = 0.66; // >= this reads as maximally busy -> 0.0
function backgroundClutterScore(stats) {
  if (!stats) return null;
  return clamp01((CLUTTER_BUSYNESS_BUSY - stats.edge_busyness) / (CLUTTER_BUSYNESS_BUSY - CLUTTER_BUSYNESS_CLEAN));
}

function technicalQualityScore(stats) {
  if (!stats) return null;
  return weightedMean([
    [lightingScore(stats), TECHNICAL_WEIGHTS.lighting],
    [colorfulnessScore(stats), TECHNICAL_WEIGHTS.colorfulness],
    [backgroundClutterScore(stats), TECHNICAL_WEIGHTS.clutter],
  ]);
}

// Top-level blend. With aesthetic present, plain plan-weighted mean. While
// aesthetic is null (CLIP not built yet), technical is CLAMPED to its planned
// 25% share and domain-fit absorbs the orphaned aesthetic weight, so the trusted
// body-fit signal stays in charge instead of renormalization handing technical 56%.
function blendPrettiness({ domainFit, technical, aesthetic }) {
  const has = (v) => v !== null && v !== undefined;
  if (has(aesthetic)) {
    return weightedMean([
      [aesthetic, PLAN_BLEND.aesthetic],
      [technical, PLAN_BLEND.technical],
      [domainFit, PLAN_BLEND.domain_fit],
    ]);
  }
  if (!has(technical)) return has(domainFit) ? clamp01(domainFit) : null;
  if (!has(domainFit)) return clamp01(technical);
  const tShare = TECHNICAL_INTERIM_CAP;
  return clamp01(tShare * technical + (1 - tShare) * domainFit);
}

// full_body_visible for the DISPLAYED card (report only; the scorer never writes).
// When keypoints are available this is exact: head (nose) AND feet (an ankle) must
// both fall inside the card window. The old aggregate-pose heuristic (pose >= 0.9)
// wrongly marked headless / head-cropped bodies as full-body, so it is only a
// fallback for rows with no keypoints.
function deriveFullBodyVisible(cv, kpa) {
  if (kpa) return kpa.full_body_in_frame;
  if (!cv || cv.person_count === null) return null;
  if (cv.person_count === 0) return false;
  const pose = cv.body_coverage_pose;
  const h = cv.height_pct;
  if (cv.person_count === 1 && pose !== null && pose >= 0.9 && h !== null && h >= 0.5) return true;
  if ((pose !== null && pose < 0.5) || (h !== null && h < 0.25)) return false;
  return null;
}

function weightedMean(parts) {
  let weightSum = 0;
  let valueSum = 0;
  for (const [value, weight] of parts) {
    if (value === null || value === undefined) continue;
    weightSum += weight;
    valueSum += value * weight;
  }
  if (weightSum === 0) return null;
  return clamp01(valueSum / weightSum);
}

function scoreOne(row, metadata, cv, pixelStats, cropSpecOverride, kpa) {
  const cropSpec = cropSpecOverride !== undefined ? cropSpecOverride : parseCropSpec(row.crop_spec);
  // A realized crop (manual now, auto later) carries a position, so score the
  // actual displayed window. Without one, score the position-independent
  // best-achievable ceiling rather than a naive centered crop.
  const hasRealizedCrop = Boolean(
    cropSpec &&
      (cropSpec.mode === "cover-window" ||
        cropSpec.windowWPct != null ||
        cropSpec.objectPositionXPct != null ||
        cropSpec.object_position_x_pct != null ||
        cropSpec.objectPositionYPct != null ||
        cropSpec.object_position_y_pct != null),
  );
  let geom = null;
  let cropBasis = null;
  if (cv && cv.height_pct) {
    if (hasRealizedCrop) {
      geom = estimateBodyAfterCrop({
        imgWidth: metadata?.width,
        imgHeight: metadata?.height,
        heightPct: cv.height_pct,
        areaPct: cv.area_pct,
        cropSpec,
      });
      cropBasis = "realized_crop_spec";
    } else {
      geom = estimateBestAchievableCrop({
        imgWidth: metadata?.width,
        imgHeight: metadata?.height,
        heightPct: cv.height_pct,
        areaPct: cv.area_pct,
      });
      cropBasis = "best_achievable_ceiling";
    }
  }
  const components = {
    aspect_score: aspectScore(metadata?.width, metadata?.height),
    resolution_score: resolutionScore(metadata?.width, metadata?.height),
    body_visible_score: bodyVisibleScore(cv, kpa),
    body_card_coverage_score: bodyCardCoverageScore(geom),
    composition_score: compositionScore(kpa),
    face_visible_score: faceVisibleScore(cv),
    // Technical bucket: deterministic lighting + colorfulness + coarse clutter.
    lighting_score: lightingScore(pixelStats),
    colorfulness_score: colorfulnessScore(pixelStats),
    background_clutter_score: backgroundClutterScore(pixelStats),
    technical_quality_score: technicalQualityScore(pixelStats),
    // Smiling needs a face-expression model run over the images; no expression
    // signal exists in the CV checkpoints, so it stays null (pending), like CLIP.
    smile_score: null,
    // Aesthetic (CLIP) deferred to Phase 1; recorded null so the blend is transparent.
    aesthetic_score: null,
  };
  const domainFit = weightedMean([
    [components.aspect_score, DOMAIN_FIT_WEIGHTS.aspect],
    [components.resolution_score, DOMAIN_FIT_WEIGHTS.resolution],
    [components.body_visible_score, DOMAIN_FIT_WEIGHTS.body_visible],
    [components.body_card_coverage_score, DOMAIN_FIT_WEIGHTS.body_card_coverage],
    [components.composition_score, DOMAIN_FIT_WEIGHTS.composition],
    [components.face_visible_score, DOMAIN_FIT_WEIGHTS.face_visible],
  ]);
  const prettiness = blendPrettiness({
    domainFit,
    technical: components.technical_quality_score,
    aesthetic: components.aesthetic_score,
  });
  return {
    domain_fit_score: round(domainFit),
    technical_quality_score: round(components.technical_quality_score),
    prettiness_score: round(prettiness),
    components: Object.fromEntries(Object.entries(components).map(([k, v]) => [k, round(v)])),
    derived_full_body_visible: deriveFullBodyVisible(cv, kpa),
    keypoint_frame: kpa
      ? {
          head_in_frame: kpa.head_in_frame,
          feet_in_frame: kpa.feet_in_frame,
          head_present: kpa.head_present,
          feet_present: kpa.feet_present,
          subject_cx: round(kpa.subject_cx),
          headroom: round(kpa.headroom),
        }
      : null,
    crop_geometry: geom
      ? {
          crop_basis: cropBasis,
          retained_height: round(geom.retainedHeight),
          retained_width: round(geom.retainedWidth),
          card_coverage: round(geom.cardCoverage),
          person_center_assumed: geom.person_center_assumed,
          best_achievable: Boolean(geom.best_achievable),
        }
      : null,
    cv_metrics: cv
      ? {
          person_count: cv.person_count,
          height_pct: cv.height_pct,
          area_pct: cv.area_pct,
          body_coverage_pose: cv.body_coverage_pose,
          has_face: cv.has_face,
          face_conf: cv.face_conf ?? null,
        }
      : null,
  };
}

function scoreRow(row, cvIndex, autoCropMap, kpIndex) {
  const cv = row.review_row_key ? cvIndex[row.review_row_key] || null : null;
  const kpEntry = kpIndex ? kpIndex[String(row.id)] || null : null;
  // Effective crop_spec: a loaded autocrop window overrides the DB value.
  const autoSpec = autoCropMap ? autoCropMap.get(String(row.id)) || null : null;
  const cropSpec = autoSpec || parseCropSpec(row.crop_spec);
  const cropSource = autoSpec ? "auto" : row.crop_spec ? "db" : "none";
  return fetchImagePrefix(row.original_url_display, { full: pixelsEnabled })
    .then(async (fetched) => {
      const base = { image_id: row.id, image_url: row.original_url_display, cv_matched: Boolean(cv) };
      if (!fetched.ok) return { ...base, skipped: true, skip_reason: `http_${fetched.status}` };
      const metadata = parseImageMetadata(fetched.bytes, fetched.content_type);
      if (!metadata.width || !metadata.height) {
        return { ...base, skipped: true, skip_reason: "no_dimensions", content_type: fetched.content_type };
      }
      // Decode for lighting/clutter stats. With a crop_spec we measure the CARD
      // window (post-autocrop) so the signals reflect what users actually see; a
      // decode failure leaves the technical bucket null (skipped + renormalized)
      // rather than dropping the whole row.
      const cropWindow = cropSpec ? cropWindowFractions(metadata.width, metadata.height, cropSpec) : null;
      const scoreOnCard = Boolean(cropWindow && cropWindow.mode !== "centered-cover");
      // Head/feet/composition analysis is done in the SAME frame the pixels are
      // measured in: the card window when we score the card, else the full source.
      const kpa = kpEntry ? analyzeKeypoints(kpEntry, scoreOnCard ? cropWindow : null) : null;
      let pixelStats = null;
      let fullPixelStats = null;
      let pixelError = null;
      if (pixelsEnabled) {
        try {
          pixelStats = await computePixelStats(fetched.bytes, scoreOnCard ? { crop: cropWindow } : {});
          if (compareCard && scoreOnCard) fullPixelStats = await computePixelStats(fetched.bytes);
        } catch (error) {
          pixelError = String(error?.message || error);
        }
      }
      const scored = scoreOne(row, metadata, cv, pixelStats, cropSpec, kpa);
      const compare =
        compareCard && fullPixelStats
          ? {
              technical_full: round(technicalQualityScore(fullPixelStats)),
              lighting_full: round(lightingScore(fullPixelStats)),
              clutter_full: round(backgroundClutterScore(fullPixelStats)),
              technical_card_minus_full: round(
                technicalQualityScore(pixelStats) - technicalQualityScore(fullPixelStats),
              ),
            }
          : null;
      return {
        ...base,
        source_file: row.source_file || null,
        existing_prettiness_score: row.prettiness_score ?? null,
        skipped: false,
        crop_source: cropSource,
        scored_card_window: scoreOnCard,
        crop_window_mode: cropWindow?.mode || null,
        crop_window: scoreOnCard ? cropWindow : null,
        pixel_stats_ok: Boolean(pixelStats),
        pixel_error: pixelError,
        compare,
        dimensions: { width: metadata.width, height: metadata.height, format: metadata.format || null },
        ...scored,
      };
    })
    .catch((error) => ({
      image_id: row.id,
      image_url: row.original_url_display,
      cv_matched: Boolean(cv),
      skipped: true,
      skip_reason: error?.name === "AbortError" ? "timeout" : "fetch_error",
      error: String(error?.message || error),
    }));
}

function quantile(sortedValues, q) {
  if (!sortedValues.length) return null;
  const pos = (sortedValues.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  const next = sortedValues[base + 1];
  return next !== undefined ? sortedValues[base] + rest * (next - sortedValues[base]) : sortedValues[base];
}

function summarize(results) {
  const scored = results.filter((r) => !r.skipped);
  const scores = scored.map((r) => r.prettiness_score).filter((v) => v !== null).sort((a, b) => a - b);
  const componentNames = [
    "aspect_score",
    "resolution_score",
    "body_visible_score",
    "body_card_coverage_score",
    "composition_score",
    "face_visible_score",
    "lighting_score",
    "colorfulness_score",
    "background_clutter_score",
    "technical_quality_score",
  ];
  const componentStats = {};
  for (const name of componentNames) {
    const vals = scored.map((r) => r.components?.[name]).filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
    componentStats[name] = {
      count: vals.length,
      mean: vals.length ? round(vals.reduce((a, b) => a + b, 0) / vals.length) : null,
      median: round(quantile(vals, 0.5)),
    };
  }
  const skipReasons = {};
  for (const r of results.filter((r) => r.skipped)) {
    skipReasons[r.skip_reason || "unknown"] = (skipReasons[r.skip_reason || "unknown"] || 0) + 1;
  }
  const fullBody = { true: 0, false: 0, null: 0 };
  for (const r of scored) fullBody[String(r.derived_full_body_visible)] = (fullBody[String(r.derived_full_body_visible)] || 0) + 1;
  // Keypoint framing diagnostics: how often the displayed card actually shows the
  // head and feet. head_cut = head present in source but not inside the card.
  const kpRows = scored.filter((r) => r.keypoint_frame);
  const headCut = kpRows.filter((r) => r.keypoint_frame.head_present && !r.keypoint_frame.head_in_frame).length;
  const feetCut = kpRows.filter((r) => r.keypoint_frame.feet_present && !r.keypoint_frame.feet_in_frame).length;
  const keypointFraming = {
    rows_with_keypoints: kpRows.length,
    head_in_frame: kpRows.filter((r) => r.keypoint_frame.head_in_frame).length,
    feet_in_frame: kpRows.filter((r) => r.keypoint_frame.feet_in_frame).length,
    head_present_but_cut_by_card: headCut,
    feet_present_but_cut_by_card: feetCut,
    full_body_in_frame: kpRows.filter((r) => r.keypoint_frame.head_in_frame && r.keypoint_frame.feet_in_frame).length,
  };
  return {
    scanned: results.length,
    scored: scored.length,
    skipped: results.length - scored.length,
    skip_reasons: skipReasons,
    cv_matched: results.filter((r) => r.cv_matched).length,
    cv_unmatched: results.filter((r) => !r.cv_matched).length,
    pixel_stats_ok: scored.filter((r) => r.pixel_stats_ok).length,
    pixel_stats_failed: scored.filter((r) => r.pixel_stats_ok === false).length,
    derived_full_body_visible_counts: fullBody,
    keypoint_framing: keypointFraming,
    score_distribution: {
      min: scores.length ? round(scores[0]) : null,
      p10: round(quantile(scores, 0.1)),
      median: round(quantile(scores, 0.5)),
      mean: scores.length ? round(scores.reduce((a, b) => a + b, 0) / scores.length) : null,
      p90: round(quantile(scores, 0.9)),
      max: scores.length ? round(scores[scores.length - 1]) : null,
    },
    component_stats: componentStats,
  };
}

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function reviewBuckets(results) {
  const scored = results.filter((r) => !r.skipped).sort((a, b) => b.prettiness_score - a.prettiness_score);
  const n = Math.min(reviewBucketSize, scored.length);
  const midStart = Math.max(0, Math.floor(scored.length / 2 - n / 2));
  return {
    top: scored.slice(0, n),
    middle: scored.slice(midStart, midStart + n),
    bottom: scored.slice(Math.max(0, scored.length - n)),
  };
}

// Render the displayed card: when we scored the autocrop window, position the
// source image so that window fills the 3:4 frame (matches the cover-window model);
// otherwise object-fit: cover (centered).
function frameImg(result) {
  const w = result.crop_window;
  if (w && w.widthFrac && w.heightFrac) {
    const widthPct = (100 / w.widthFrac).toFixed(2);
    const heightPct = (100 / w.heightFrac).toFixed(2);
    const leftPct = (-(w.leftFrac / w.widthFrac) * 100).toFixed(2);
    const topPct = (-(w.topFrac / w.heightFrac) * 100).toFixed(2);
    return `<img class="win" src="${htmlEscape(result.image_url)}" loading="lazy" style="width:${widthPct}%;height:${heightPct}%;left:${leftPct}%;top:${topPct}%;">`;
  }
  return `<img src="${htmlEscape(result.image_url)}" loading="lazy">`;
}

function card(result) {
  const c = result.components || {};
  const g = result.crop_geometry;
  const coverageLine = g
    ? `cover ${htmlEscape(g.card_coverage)} &middot; keepH ${htmlEscape(g.retained_height)}`
    : "no CV";
  const cmp = result.compare;
  const cmpLine = cmp
    ? `<div class="cmp">card vs full: tech ${htmlEscape(result.technical_quality_score)} vs ${htmlEscape(cmp.technical_full)} (${cmp.technical_card_minus_full >= 0 ? "+" : ""}${htmlEscape(cmp.technical_card_minus_full)}) &middot; clutter ${htmlEscape(c.background_clutter_score)} vs ${htmlEscape(cmp.clutter_full)}</div>`
    : "";
  return `
    <article class="card" data-score="${htmlEscape(result.prettiness_score ?? 0)}">
      <div class="frame">${frameImg(result)}</div>
      <div class="score">${htmlEscape(result.prettiness_score)} <span class="src">${htmlEscape(result.crop_source)}</span></div>
      <div class="meta">
        <div>${htmlEscape(result.dimensions?.width)}&times;${htmlEscape(result.dimensions?.height)} ${htmlEscape(result.dimensions?.format || "")}</div>
        <div>aspect ${htmlEscape(c.aspect_score)} &middot; res ${htmlEscape(c.resolution_score)}</div>
        <div>body ${htmlEscape(c.body_visible_score)} &middot; cardfit ${htmlEscape(c.body_card_coverage_score)} &middot; comp ${htmlEscape(c.composition_score)} &middot; face ${htmlEscape(c.face_visible_score)}</div>
        <div>light ${htmlEscape(c.lighting_score)} &middot; color ${htmlEscape(c.colorfulness_score)} &middot; clutter ${htmlEscape(c.background_clutter_score)} &middot; tech ${htmlEscape(c.technical_quality_score)}</div>
        ${cmpLine}
        <div>${coverageLine}</div>
        <div class="site">fullbody=${htmlEscape(result.derived_full_body_visible)} &middot; head=${htmlEscape(result.keypoint_frame?.head_in_frame)} feet=${htmlEscape(result.keypoint_frame?.feet_in_frame)}</div>
      </div>
    </article>`;
}

function buildReviewHtml(report, buckets, gallery) {
  const section = (title, rows) =>
    `<section><h2>${htmlEscape(title)} (${rows.length})</h2><div class="grid">${rows.map(card).join("")}</div></section>`;
  const gallerySection = `<section id="gallery"><h2>All scored (sorted, ${gallery.length}) &mdash; <span id="visibleCount">${gallery.length}</span> shown</h2><div class="grid">${gallery.map(card).join("")}</div></section>`;
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FWM Dev Prettiness Score Dry-Run (${htmlEscape(report.prettiness_model_version)})</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; color: #1f2933; }
    header { margin-bottom: 16px; }
    h2 { font-size: 16px; border-bottom: 1px solid #d9e2ec; padding-bottom: 4px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin: 12px 0 28px; }
    .card { border: 1px solid #d9e2ec; border-radius: 8px; overflow: hidden; background: #fff; }
    .frame { position: relative; aspect-ratio: 3 / 4; overflow: hidden; background: #f0f4f8; }
    .frame img { width: 100%; height: 100%; object-fit: cover; }
    .frame img.win { position: absolute; max-width: none; object-fit: fill; }
    .score { font-weight: 700; font-size: 18px; padding: 6px 8px 0; }
    .score .src { font-weight: 400; font-size: 11px; color: #9aa5b1; }
    .cmp { color: #2f855a; }
    .meta { font-size: 11px; color: #52606d; padding: 2px 8px 8px; }
    .site { color: #9aa5b1; overflow-wrap: anywhere; }
    pre { white-space: pre-wrap; font-size: 11px; background: #f8fafc; padding: 8px; }
    .slider-bar { position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid #d9e2ec;
      padding: 12px 0; margin-bottom: 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .slider-bar input[type=range] { flex: 1; min-width: 220px; max-width: 480px; }
    .slider-bar .thresh { font-weight: 700; font-variant-numeric: tabular-nums; min-width: 3.2em; }
    .slider-bar label { font-size: 14px; }
    .card.hidden { display: none; }
    section.empty { display: none; }
  </style>
</head>
<body>
  <header>
    <h1>FWM Dev Prettiness Score Dry-Run</h1>
    <p>Generated ${htmlEscape(report.generated_at)}. Model: ${htmlEscape(report.prettiness_model_version)} (${report.pixels_enabled ? "domain-fit + technical proxy; aesthetic pending" : "domain-fit only; aesthetic + technical pending"}).</p>
    <p>CV matched ${htmlEscape(report.summary.cv_matched)} / unmatched ${htmlEscape(report.summary.cv_unmatched)}. Cards with a DB crop_spec are scored on the post-autocrop card window; without one, card coverage uses the best-achievable 3:4 crop (croppability ceiling).</p>
    <pre>${htmlEscape(JSON.stringify(report.summary, null, 2))}</pre>
  </header>
  <div class="slider-bar">
    <label for="prettySlider">Min prettiness</label>
    <input type="range" id="prettySlider" min="0" max="1" step="0.01" value="0">
    <span class="thresh" id="threshLabel">0.00</span>
    <span id="shownLabel"></span>
  </div>
  ${gallerySection}
  ${section("Top scores", buckets.top)}
  ${section("Middle scores", buckets.middle)}
  ${section("Bottom scores", buckets.bottom)}
  <script>
    (function () {
      var slider = document.getElementById("prettySlider");
      var threshLabel = document.getElementById("threshLabel");
      var shownLabel = document.getElementById("shownLabel");
      var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));
      var sections = Array.prototype.slice.call(document.querySelectorAll("section"));
      function apply() {
        var t = parseFloat(slider.value);
        threshLabel.textContent = t.toFixed(2);
        var total = cards.length;
        var shown = 0;
        cards.forEach(function (c) {
          var s = parseFloat(c.getAttribute("data-score")) || 0;
          var hide = s < t;
          c.classList.toggle("hidden", hide);
          if (!hide) shown++;
        });
        shownLabel.textContent = shown + " / " + total + " images at or above this score";
        var vc = document.getElementById("visibleCount");
        sections.forEach(function (sec) {
          var visible = sec.querySelectorAll(".card:not(.hidden)").length;
          sec.classList.toggle("empty", visible === 0);
          if (sec.id === "gallery" && vc) vc.textContent = visible;
        });
      }
      slider.addEventListener("input", apply);
      apply();
    })();
  </script>
</body>
</html>
`;
}

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function buildCsv(results) {
  const headers = [
    "image_id",
    "image_url",
    "source_file",
    "cv_matched",
    "skipped",
    "skip_reason",
    "prettiness_score",
    "domain_fit_score",
    "technical_quality_score",
    "crop_source",
    "scored_card_window",
    "technical_full",
    "technical_card_minus_full",
    "aspect_score",
    "resolution_score",
    "body_visible_score",
    "body_card_coverage_score",
    "composition_score",
    "face_visible_score",
    "lighting_score",
    "colorfulness_score",
    "background_clutter_score",
    "derived_full_body_visible",
    "head_in_frame",
    "feet_in_frame",
    "has_face",
    "card_coverage",
    "retained_height",
    "width",
    "height",
    "format",
  ];
  const lines = results.map((r) =>
    [
      r.image_id,
      r.image_url,
      r.source_file,
      r.cv_matched,
      r.skipped,
      r.skip_reason,
      r.prettiness_score,
      r.domain_fit_score,
      r.technical_quality_score,
      r.crop_source,
      r.scored_card_window,
      r.compare?.technical_full,
      r.compare?.technical_card_minus_full,
      r.components?.aspect_score,
      r.components?.resolution_score,
      r.components?.body_visible_score,
      r.components?.body_card_coverage_score,
      r.components?.composition_score,
      r.components?.face_visible_score,
      r.components?.lighting_score,
      r.components?.colorfulness_score,
      r.components?.background_clutter_score,
      r.derived_full_body_visible,
      r.keypoint_frame?.head_in_frame,
      r.keypoint_frame?.feet_in_frame,
      r.cv_metrics?.has_face,
      r.crop_geometry?.card_coverage,
      r.crop_geometry?.retained_height,
      r.dimensions?.width,
      r.dimensions?.height,
      r.dimensions?.format,
    ]
      .map(csvCell)
      .join(","),
  );
  return [headers.join(","), ...lines].join("\n") + "\n";
}

// Aggregate the card-vs-full-source technical comparison (only rows where both
// were measured, i.e. an autocrop window was applied).
function cardVsFullSummary(results) {
  const rows = results.filter((r) => !r.skipped && r.compare);
  if (!rows.length) return { count: 0 };
  const mean = (pick) => round(rows.reduce((a, r) => a + (pick(r) ?? 0), 0) / rows.length);
  const improved = rows.filter((r) => (r.compare.technical_card_minus_full ?? 0) > 0).length;
  return {
    count: rows.length,
    technical_card_mean: mean((r) => r.technical_quality_score),
    technical_full_mean: mean((r) => r.compare.technical_full),
    technical_delta_mean: mean((r) => r.compare.technical_card_minus_full),
    clutter_card_mean: mean((r) => r.components?.background_clutter_score),
    clutter_full_mean: mean((r) => r.compare.clutter_full),
    improved_by_crop: improved,
    worsened_or_same: rows.length - improved,
  };
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Prettiness scorer guard" });

  console.log(rebuildCvCache ? "Rebuilding workbook CV index..." : "Loading workbook CV index...");
  const cvIndex = await loadWorkbookCvIndex({ cwd: repoRoot, rebuild: rebuildCvCache });
  console.log(
    `CV index: ${cvIndex.meta.indexed_keys ?? Object.keys(cvIndex.byKey).length} keys (${cvIndex.meta.cache_hit ? "cache" : "rebuilt"}).`,
  );

  console.log(rebuildKpCache ? "Rebuilding keypoint index..." : "Loading keypoint index...");
  let kpIndex = null;
  let kpMeta = null;
  try {
    const loaded = await loadKeypointIndex({ cwd: repoRoot, rebuild: rebuildKpCache });
    kpIndex = loaded.byId;
    kpMeta = loaded.meta;
    console.log(
      `Keypoint index: ${kpMeta.indexed_ids ?? Object.keys(kpIndex).length} ids (${kpMeta.cache_hit ? "cache" : "rebuilt"}).`,
    );
  } catch (error) {
    console.warn(`Keypoint index unavailable (${error.message || error}); head/feet/composition will be null.`);
  }

  let autoCropMap = null;
  let autoCropModel = null;
  if (autoCropsPath) {
    const loaded = await loadAutoCropMap(autoCropsPath);
    autoCropMap = loaded.map;
    autoCropModel = loaded.model;
    console.log(`Auto-crop map: ${autoCropMap.size} crop_specs from ${autoCropsPath} (model ${autoCropModel}).`);
  }
  const restrictIds = onlyAutoCrops && autoCropMap ? [...autoCropMap.keys()] : null;
  if (restrictIds) console.log(`Restricting to ${restrictIds.length} autocropped ids.`);

  const rows = await fetchCandidateRows(guard, restrictIds);
  const results = [];
  for (const row of rows) results.push(await scoreRow(row, cvIndex.byKey, autoCropMap, kpIndex));

  const summary = summarize(results);
  const buckets = reviewBuckets(results);

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const stem = `dev_image_prettiness_score_dryrun_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const reportPath = path.join(reportsDir, `${stem}.json`);
  const reviewHtmlPath = path.join(reportsDir, `${stem}.html`);
  const reviewCsvPath = path.join(reportsDir, `${stem}_review.csv`);

  const report = {
    generated_at: generatedAt,
    mode: "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    prettiness_model_version: PRETTINESS_MODEL_VERSION,
    pixels_enabled: pixelsEnabled,
    auto_crops_path: autoCropsPath,
    auto_crop_model: autoCropModel,
    auto_crops_loaded: autoCropMap ? autoCropMap.size : 0,
    scored_card_window_count: results.filter((r) => !r.skipped && r.scored_card_window).length,
    card_vs_full: compareCard ? cardVsFullSummary(results) : null,
    plan_target_blend: PLAN_BLEND,
    domain_fit_weights: DOMAIN_FIT_WEIGHTS,
    technical_weights: pixelsEnabled ? TECHNICAL_WEIGHTS : null,
    lighting_weights: pixelsEnabled ? LIGHTING_WEIGHTS : null,
    technical_interim_cap: TECHNICAL_INTERIM_CAP,
    blend_note:
      "Aesthetic (CLIP) is not built. While it is null, technical is clamped to its planned 25% share and domain-fit absorbs the orphaned aesthetic weight (~75%), so prettiness = 0.25*technical + 0.75*domain_fit (not the 56% technical that renormalization would give).",
    clutter_note:
      "background_clutter_score is a COARSE whole-frame edge-busyness proxy. With no person bbox position in the CV checkpoint it cannot isolate the background, so a busy outfit/pattern reads as clutter too. Weighted lowest (0.3 of technical) and pending the CV re-run that adds a person mask.",
    colorfulness_note:
      "colorfulness_score is the Hasler-Susstrunk colorfulness of the scored window (card when an autocrop exists), normalized to 0..1. Deterministic, no ML.",
    face_note:
      "face_visible_score is NULL/pending: has_face_yunet exists in the checkpoint header but is EMPTY in 100% of the 326k rows (YuNet face detection was never populated). The scorer is wired to use it (visible face -> higher, no face -> 0) the moment a face-detection pass fills it, but today it has no data, so the component is skipped + renormalized.",
    smile_note:
      "smile_score is NULL/pending: there is NO smile/expression signal anywhere in the CV checkpoints. Like face_visible, rewarding smiles requires a new face/expression model pass over the images (similar to the YOLO detection run). Tracked as a pending component.",
    brightness_note:
      "brightnessScore was retuned to reward a brighter, 'light' frame (sweet spot ~120-195 luma); blown-out frames are still penalized via exposure highlight-clipping.",
    body_visible_note:
      "body_visible_score and derived_full_body_visible are now KEYPOINT-AWARE: head (nose) and feet (ankles) must fall inside the displayed card window. The old aggregate body_coverage_pose alone rated a headless or head-cropped body ~0.9 and marked it full-body (the bug). A head cut off by the card now penalizes body_visible hard (x0.4) and sets full_body_visible=false.",
    composition_note:
      "composition_score (keypoint-only) rewards a horizontally centered subject with head + feet in frame and sensible headroom. Modest weight (0.1 of domain-fit).",
    keypoint_index_meta: kpMeta,
    pending_components: pixelsEnabled
      ? ["aesthetic_score", "face_visible_score", "smile_score"]
      : ["aesthetic_score", "technical_quality_score", "face_visible_score", "smile_score"],
    cv_index_meta: cvIndex.meta,
    card_coverage_basis:
      "Without a realized crop_spec, body_card_coverage uses the position-independent best-achievable 3:4 crop (croppability ceiling), since YOLO metrics have no bbox position. Rows with a crop_spec are scored against that realized window.",
    limit,
    timeout_ms: timeoutMs,
    review_bucket_size: reviewBucketSize,
    review_html_path: reviewHtmlPath,
    review_csv_path: reviewCsvPath,
    summary,
    results,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  const gallery = results.filter((r) => !r.skipped).sort((a, b) => (b.prettiness_score ?? 0) - (a.prettiness_score ?? 0));
  await writeFile(reviewHtmlPath, buildReviewHtml(report, buckets, gallery), "utf8");
  await writeFile(reviewCsvPath, buildCsv(results), "utf8");

  console.log(`Wrote prettiness score dry-run report: ${reportPath}`);
  console.log(`Wrote prettiness review HTML: ${reviewHtmlPath}`);
  console.log(`Wrote prettiness review CSV: ${reviewCsvPath}`);
  console.log(
    `Model: ${PRETTINESS_MODEL_VERSION} (${pixelsEnabled ? "domain-fit + technical proxy; aesthetic pending" : "domain-fit only"})`,
  );
  console.log(`Scanned ${summary.scanned}, scored ${summary.scored}, skipped ${summary.skipped}`);
  console.log(`CV matched ${summary.cv_matched}, unmatched ${summary.cv_unmatched}`);
  if (pixelsEnabled) console.log(`Pixel stats ok ${summary.pixel_stats_ok}, failed ${summary.pixel_stats_failed}`);
  if (autoCropMap) {
    console.log(`Scored card window (autocrop) on ${report.scored_card_window_count} rows.`);
    if (report.card_vs_full) {
      const cf = report.card_vs_full;
      console.log(
        `Card vs full source — technical ${cf.technical_card_mean} vs ${cf.technical_full_mean} (Δ ${cf.technical_delta_mean}); ` +
          `clutter ${cf.clutter_card_mean} vs ${cf.clutter_full_mean}; improved ${cf.improved_by_crop}/${cf.count}.`,
      );
    }
  }
  console.log(`Score distribution: ${JSON.stringify(summary.score_distribution)}`);
  console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
