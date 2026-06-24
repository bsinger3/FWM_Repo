// Maps a garment taxonomy (mother category + specific clothing type) plus pose
// keypoints to the vertical body band the crop should keep when the whole body
// can't fit a 3:4 card. e.g. for jeans we keep waist->ankles (sacrificing the
// head); for a blouse we keep the shoulders->hem of the top.
//
// All inputs/outputs are image fractions (0..1, y increasing downward). Keypoints
// are { name: yFrac } with any missing/low-confidence point left null; anchors
// then fall back to fractions of the person bounding box.

function avg(a, b) {
  if (a != null && b != null) return (a + b) / 2;
  return a != null ? a : b != null ? b : null;
}

// Anchor y-fractions for the body, from keypoints where available else bbox-based
// estimates (typical standing-person proportions).
export function bodyAnchors(keypoints = {}, personBox) {
  const bt = personBox.top;
  const bh = personBox.height;
  const bb = bt + bh;
  const shoulders = avg(keypoints.left_shoulder, keypoints.right_shoulder) ?? bt + 0.16 * bh;
  const hips = avg(keypoints.left_hip, keypoints.right_hip) ?? bt + 0.5 * bh;
  const knees = avg(keypoints.left_knee, keypoints.right_knee) ?? bt + 0.72 * bh;
  const ankles = (() => {
    const a = keypoints.left_ankle;
    const b = keypoints.right_ankle;
    if (a != null && b != null) return Math.max(a, b);
    return a != null ? a : b != null ? b : bb;
  })();
  return {
    headTop: bt,
    shoulders: Math.max(bt, shoulders),
    hips: Math.min(bb, hips),
    knees: Math.min(bb, knees),
    feet: Math.min(1, Math.max(knees, ankles) + 0.02),
    top: bt,
    bottom: bb,
  };
}

// Breathing room added around every band so the crop won't clip the garment.
// Biased to the top because clipping a waistband / neckline reads worst.
const GARMENT_TOP_MARGIN = 0.09;
const GARMENT_BOTTOM_MARGIN = 0.03;
// How far above the hip keypoint a waistband typically sits (fraction of torso);
// high-waisted bottoms sit well above the hip joint.
const WAIST_RISE = 0.16;

// Specific clothing types that override their mother-category default band.
const TYPE_OVERRIDES = {
  shorts: (a) => ({ top: a.hips - WAIST_RISE * (a.hips - a.shoulders), bottom: a.knees, label: "waist-to-knee" }),
  skirt: (a) => ({ top: a.hips - WAIST_RISE * (a.hips - a.shoulders), bottom: a.knees, label: "waist-to-knee" }),
  "sports-bra": (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.hips, label: "shoulders-to-waist" }),
  bra: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.hips, label: "shoulders-to-waist" }),
  bralette: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.hips, label: "shoulders-to-waist" }),
  "yoga-pants": (a) => ({ top: a.hips - WAIST_RISE * (a.hips - a.shoulders), bottom: a.feet, label: "waist-to-ankle" }),
};

// Mother-category default bands.
const CATEGORY_BANDS = {
  tops: (a) => ({ top: a.shoulders - 0.25 * (a.shoulders - a.headTop), bottom: a.hips + 0.18 * (a.knees - a.hips), label: "shoulders-to-hem" }),
  bodysuits: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.hips, label: "shoulders-to-hip" }),
  intimates: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.hips, label: "shoulders-to-waist" }),
  swimwear: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.hips, label: "shoulders-to-hip" }),
  bottoms: (a) => ({ top: a.hips - WAIST_RISE * (a.hips - a.shoulders), bottom: a.feet, label: "waist-to-ankle" }),
  outerwear: (a) => ({ top: a.shoulders - 0.3 * (a.shoulders - a.headTop), bottom: a.knees, label: "shoulders-to-knee" }),
  dresses: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.feet, label: "shoulders-to-ankle" }),
  jumpsuits: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.feet, label: "shoulders-to-ankle" }),
  sets: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.feet, label: "shoulders-to-ankle" }),
  activewear: (a) => ({ top: a.shoulders - 0.2 * (a.shoulders - a.headTop), bottom: a.feet, label: "shoulders-to-ankle" }),
  shoes: (a) => ({ top: a.knees, bottom: Math.min(1, a.feet + 0.04), label: "knee-to-feet" }),
  // accessories / other -> no garment band (caller keeps the head / whole body).
};

// Returns { top, bottom, label, source } in image fractions, or null when the
// category gives no useful garment band (accessories/other/unknown).
export function garmentRegion({ motherCategory, clothingType, keypoints, personBox }) {
  if (!personBox) return null;
  const anchors = bodyAnchors(keypoints || {}, personBox);
  let band = null;
  let source = null;
  if (clothingType && TYPE_OVERRIDES[clothingType]) {
    band = TYPE_OVERRIDES[clothingType](anchors);
    source = `type:${clothingType}`;
  } else if (motherCategory && CATEGORY_BANDS[motherCategory]) {
    band = CATEGORY_BANDS[motherCategory](anchors);
    source = `category:${motherCategory}`;
  }
  if (!band) return null;
  let top = Math.max(0, Math.min(band.top, band.bottom));
  let bottom = Math.min(1, Math.max(band.top, band.bottom));
  const h = bottom - top;
  top = Math.max(0, top - GARMENT_TOP_MARGIN * h);
  bottom = Math.min(1, bottom + GARMENT_BOTTOM_MARGIN * h);
  if (bottom - top < 0.02) return null;
  return { top, bottom, label: band.label, source };
}
