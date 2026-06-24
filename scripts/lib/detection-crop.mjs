// Shared crop-decision logic so the review dashboard and the backfill writer
// produce IDENTICAL crops from the same detection rows. Both import decideCrop().

import { garmentRegion } from "./garment-region.mjs";
import { solveAutoCrop } from "./card-crop-geometry.mjs";

// clothing_type_id values on images that aren't ids in the tag catalog.
export const TYPE_ALIASES = { swimsuit: "swimwear", "one-piece": "swimwear", tee: "tops", cami: "tops" };

// Only these solver modes are safe to write. head_priority means the body didn't
// fit AND we had no usable garment region (missing taxonomy or sparse keypoints),
// so the crop would be a guess — skip it.
export const WRITABLE_MODES = new Set(["whole_body", "garment_priority", "garment_partial"]);

// Pose keypoints arrive as [x, y, conf] pixels; the garment-region mapping only
// needs vertical anchors, so expose y as a fraction of image height.
export function keypointYFractions(rec) {
  const out = {};
  const kp = rec.keypoints || {};
  for (const [name, val] of Object.entries(kp)) {
    if (val && rec.img_height) out[name] = val[1] / rec.img_height;
  }
  return out;
}

// Person box (fractions) from the detect bbox, unioned with head (nose) and feet
// (ankle) keypoints so a slightly tight YOLO box never clips the real extremities.
export function personBoxFractions(rec) {
  const w = rec.img_width;
  const h = rec.img_height;
  if (!w || !h || !rec.bbox_xyxy) return null;
  const [x1, y1, x2, y2] = rec.bbox_xyxy;
  let left = x1 / w;
  let top = y1 / h;
  let right = x2 / w;
  let bottom = y2 / h;
  const kp = rec.keypoints || {};
  const pts = [kp.nose, kp.left_ankle, kp.right_ankle].filter(Boolean);
  for (const p of pts) {
    left = Math.min(left, p[0] / w);
    right = Math.max(right, p[0] / w);
    top = Math.min(top, p[1] / h);
    bottom = Math.max(bottom, p[1] / h);
  }
  left = Math.max(0, left);
  top = Math.max(0, top);
  right = Math.min(1, right);
  bottom = Math.min(1, bottom);
  return { left, top, width: right - left, height: bottom - top };
}

export function resolveMotherCategory(clothingType, catalog = {}, aliases = TYPE_ALIASES) {
  if (!clothingType) return null;
  return catalog[clothingType] || aliases[clothingType] || null;
}

// Returns { skip } or { person, region, motherCategory, clothingType, crop }.
export function decideCrop(rec, { catalog = {}, aliases = TYPE_ALIASES } = {}) {
  if (rec.error) return { skip: "fetch_error" };
  if (!rec.img_width || !rec.img_height) return { skip: "no_dimensions" };
  const person = personBoxFractions(rec);
  if (!person) return { skip: "no_person" };
  const clothingType = rec.clothing_type_id || null;
  const motherCategory = resolveMotherCategory(clothingType, catalog, aliases);
  const region = garmentRegion({ motherCategory, clothingType, keypoints: keypointYFractions(rec), personBox: person });
  const crop = solveAutoCrop({ imgWidth: rec.img_width, imgHeight: rec.img_height, personBox: person, priorityRegion: region });
  if (!crop) return { skip: "no_crop" };
  return { person, region, motherCategory, clothingType, crop };
}

// The canonical stored crop_spec: the explicit window + provenance. object-position
// and zoom are dropped (redundant for cover-window; window* is authoritative).
export function cropSpecForStorage(crop, { modelVersion, scoredAt }) {
  const c = crop.crop_spec;
  return {
    mode: "cover-window",
    aspectRatio: "3:4",
    windowXPct: c.windowXPct,
    windowYPct: c.windowYPct,
    windowWPct: c.windowWPct,
    windowHPct: c.windowHPct,
    rotationDeg: c.rotationDeg ?? 0,
    source: "auto",
    cropModelVersion: modelVersion,
    scoredAt,
  };
}
