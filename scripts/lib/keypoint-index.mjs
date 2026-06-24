// Builds an index of YOLO-pose keypoints from the person-detection ndjson
// (scripts/detect_person_boxes.py output, e.g. crop_bboxes_full.ndjson), keyed by
// image id, so the prettiness scorer can reason about head/feet visibility and
// composition AFTER the autocrop — things the aggregate body_coverage_pose score
// cannot express (a headless-but-otherwise-complete body still scores ~0.9 there).
//
// Keypoints are stored normalized to fractions of the source image (xFrac, yFrac,
// conf), so they can be intersected with a crop window (also fractional). Only the
// keypoints the detector emits are kept: nose, shoulders, hips, knees, ankles.

import { createReadStream } from "node:fs";
import { mkdir, readFile, writeFile, stat } from "node:fs/promises";
import { createInterface } from "node:readline";
import path from "node:path";
import { fwmDataDir } from "../../tools/image-review-dashboard/paths.mjs";

const DEFAULT_NDJSON = path.join("_cache", "crop_bboxes_full.ndjson");
const CACHE_SUBPATH = path.join("_cache", "keypoint_index.json");
const INDEX_VERSION = "keypoint_index_v1";

// Which raw keypoints to retain (the detector's pose head emits these).
const KEEP = [
  "nose",
  "left_shoulder",
  "right_shoulder",
  "left_hip",
  "right_hip",
  "left_knee",
  "right_knee",
  "left_ankle",
  "right_ankle",
];

function normKeypoints(k, W, H) {
  if (!k || !W || !H) return null;
  const out = {};
  let any = false;
  for (const name of KEEP) {
    const v = k[name];
    if (Array.isArray(v) && v.length >= 3 && Number.isFinite(v[0]) && Number.isFinite(v[1])) {
      out[name] = [v[0] / W, v[1] / H, Number.isFinite(v[2]) ? v[2] : 0];
      any = true;
    }
  }
  return any ? out : null;
}

async function scanNdjson(ndjsonPath) {
  const rl = createInterface({ input: createReadStream(ndjsonPath, "utf8"), crlfDelay: Infinity });
  const index = {};
  let scanned = 0;
  for await (const line of rl) {
    if (!line.trim()) continue;
    let rec;
    try {
      rec = JSON.parse(line);
    } catch {
      continue;
    }
    const id = rec.id;
    if (!id) continue;
    scanned += 1;
    const kp = normKeypoints(rec.keypoints, rec.img_width, rec.img_height);
    index[String(id)] = {
      person_count: Number.isFinite(rec.person_count) ? rec.person_count : null,
      img_aspect: rec.img_width && rec.img_height ? rec.img_height / rec.img_width : null,
      keypoints: kp,
    };
  }
  return { index, scanned };
}

// Returns { byId, meta }. byId: image id -> { person_count, img_aspect, keypoints }.
// keypoints is { name: [xFrac, yFrac, conf] } in SOURCE-image fractions, or null.
export async function loadKeypointIndex({ cwd = process.cwd(), rebuild = false, ndjson = null } = {}) {
  const dataDir = fwmDataDir(cwd);
  const cachePath = path.join(dataDir, CACHE_SUBPATH);
  const ndjsonPath = ndjson || path.join(dataDir, DEFAULT_NDJSON);

  if (!rebuild) {
    try {
      const cached = JSON.parse(await readFile(cachePath, "utf8"));
      if (cached.version === INDEX_VERSION && cached.byId) {
        return { byId: cached.byId, meta: { ...cached.meta, cache_hit: true, cache_path: cachePath } };
      }
    } catch {
      // fall through to rebuild
    }
  }

  await stat(ndjsonPath).catch(() => {
    throw new Error(`Keypoint ndjson not found: ${ndjsonPath}`);
  });
  const { index, scanned } = await scanNdjson(ndjsonPath);
  const meta = {
    version: INDEX_VERSION,
    built_at: new Date().toISOString(),
    ndjson: ndjsonPath,
    scanned_rows: scanned,
    indexed_ids: Object.keys(index).length,
  };
  await mkdir(path.dirname(cachePath), { recursive: true });
  await writeFile(cachePath, JSON.stringify({ ...meta, byId: index }) + "\n", "utf8");
  return { byId: index, meta: { ...meta, cache_hit: false, cache_path: cachePath } };
}

// --- Geometry helpers over a (possibly cropped) frame ------------------------

const CONF = 0.3; // keypoint confidence floor to count a joint as "present"

function present(pt) {
  return Array.isArray(pt) && pt[2] >= CONF;
}

// Map a source-fraction keypoint into card space given a crop window
// { leftFrac, topFrac, widthFrac, heightFrac }. Returns { x, y, inside } in 0..1
// card coordinates, or null if the keypoint is absent. With no window, source
// fractions are treated as card coordinates (whole image is the "card").
function toCard(pt, win) {
  if (!present(pt)) return null;
  const [xf, yf] = pt;
  if (!win) return { x: xf, y: yf, inside: xf >= 0 && xf <= 1 && yf >= 0 && yf <= 1 };
  const x = (xf - win.leftFrac) / win.widthFrac;
  const y = (yf - win.topFrac) / win.heightFrac;
  return { x, y, inside: x >= 0 && x <= 1 && y >= 0 && y <= 1 };
}

// Analyze head/feet visibility and composition of the subject within the displayed
// frame (the card window when present, else the whole source image).
// Returns null when there are no usable keypoints.
export function analyzeKeypoints(entry, win = null) {
  const kp = entry?.keypoints;
  if (!kp) return null;
  const nose = toCard(kp.nose, win);
  const ankles = [toCard(kp.left_ankle, win), toCard(kp.right_ankle, win)].filter(Boolean);
  const shoulders = [toCard(kp.left_shoulder, win), toCard(kp.right_shoulder, win)].filter(Boolean);
  const hips = [toCard(kp.left_hip, win), toCard(kp.right_hip, win)].filter(Boolean);

  const headPresent = Boolean(nose);
  const feetPresent = ankles.length > 0;
  const headInFrame = Boolean(nose && nose.inside);
  const feetInFrame = ankles.some((a) => a.inside);

  // Subject horizontal center: mean x of shoulders+hips (torso), fallback to nose.
  const torso = [...shoulders, ...hips];
  const subjectCx = torso.length
    ? torso.reduce((s, p) => s + p.x, 0) / torso.length
    : nose
      ? nose.x
      : null;
  // Headroom: vertical gap above the head inside the frame (nose.y), only meaningful
  // when the head is in frame. ~0 means the head is jammed at / cut by the top edge.
  const headroom = headInFrame ? nose.y : null;

  return {
    head_present: headPresent,
    feet_present: feetPresent,
    head_in_frame: headInFrame,
    feet_in_frame: feetInFrame,
    full_body_in_frame: headInFrame && feetInFrame,
    subject_cx: subjectCx,
    headroom,
  };
}
