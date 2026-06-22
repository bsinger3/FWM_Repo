// Pure card-crop geometry. No I/O, no Supabase — safe to unit test and reuse.
//
// The product renders review photos into a fixed-aspect (3:4 portrait) card with
// `object-fit: cover`, so the card always shows a cropped window into the source
// image. Auto-cropping (a later phase) will set crop_spec.objectPosition/zoom to
// move that window. These helpers compute, for a given window, how much of the
// person's body survives the crop and how much of the card the body fills.
//
// We only have YOLO height/area percentages (no bbox x/y), so position is
// approximated by assuming the person is centered in the source image. Callers
// should surface that assumption in their evidence/reports.

export const CARD_ASPECT = 3 / 4; // width / height

function clamp01(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

// The visible window of a centered `object-fit: cover` crop, expressed as
// fractions of the source image. crop_spec can shift (objectPosition) and
// tighten (zoom) the window. Returns {wFrac, hFrac, xFrac, yFrac} where x/y are
// the top-left offsets into the image (0..1).
export function coverCropWindow(imgWidth, imgHeight, cropSpec = null, cardAspect = CARD_ASPECT) {
  if (!imgWidth || !imgHeight) return null;
  const imageAspect = imgWidth / imgHeight; // width / height
  let wFrac;
  let hFrac;
  if (imageAspect > cardAspect) {
    // Image is wider than the card: full height shown, width overflows (side crop).
    hFrac = 1;
    wFrac = cardAspect / imageAspect;
  } else {
    // Image is taller/narrower than the card: full width shown, height overflows
    // (top/bottom crop — this is what can cut off heads and feet).
    wFrac = 1;
    hFrac = imageAspect / cardAspect;
  }
  const zoom = Number(cropSpec?.zoom ?? cropSpec?.crop_zoom ?? 1);
  if (Number.isFinite(zoom) && zoom > 1) {
    wFrac = clamp01(wFrac / zoom);
    hFrac = clamp01(hFrac / zoom);
  }
  const posXPct = Number(cropSpec?.objectPositionXPct ?? cropSpec?.object_position_x_pct ?? 50);
  const posYPct = Number(cropSpec?.objectPositionYPct ?? cropSpec?.object_position_y_pct ?? 50);
  const xFrac = (1 - wFrac) * (Number.isFinite(posXPct) ? clamp01(posXPct / 100) : 0.5);
  const yFrac = (1 - hFrac) * (Number.isFinite(posYPct) ? clamp01(posYPct / 100) : 0.5);
  return { wFrac, hFrac, xFrac, yFrac, imageAspect };
}

// Resolve any crop_spec to the source-image crop rectangle as fractions
// { leftFrac, topFrac, widthFrac, heightFrac, mode }, for cropping the actual
// card pixels (e.g. to measure lighting/clutter on the displayed card). Handles
// the explicit cover-window model, the object-position+zoom model, and the
// no-crop default (centered cover).
export function cropWindowFractions(imgWidth, imgHeight, cropSpec = null, cardAspect = CARD_ASPECT) {
  if (!imgWidth || !imgHeight) return null;
  if (cropSpec && (cropSpec.mode === "cover-window" || cropSpec.windowWPct != null)) {
    const widthFrac = clamp01(Number(cropSpec.windowWPct) / 100);
    const heightFrac = clamp01(Number(cropSpec.windowHPct) / 100);
    const leftFrac = clamp01(Number(cropSpec.windowXPct) / 100);
    const topFrac = clamp01(Number(cropSpec.windowYPct) / 100);
    if (widthFrac && heightFrac) {
      return { leftFrac, topFrac, widthFrac, heightFrac, mode: "cover-window" };
    }
  }
  const w = coverCropWindow(imgWidth, imgHeight, cropSpec, cardAspect);
  if (!w) return null;
  return {
    leftFrac: w.xFrac,
    topFrac: w.yFrac,
    widthFrac: w.wFrac,
    heightFrac: w.hFrac,
    mode: cropSpec ? "object-position" : "centered-cover",
  };
}

// Person bounding box as fractions of the source image, assuming the person is
// centered. heightPct and areaPct are the YOLO main-person metrics (0..1).
export function personBoxFromMetrics(heightPct, areaPct) {
  const bhFrac = clamp01(heightPct);
  if (!bhFrac) return null;
  const bwFrac = clamp01(areaPct / bhFrac); // area = h * w  ->  w = area / h
  if (!bwFrac) return null;
  return {
    bwFrac,
    bhFrac,
    left: (1 - bwFrac) / 2,
    top: (1 - bhFrac) / 2,
    right: 1 - (1 - bwFrac) / 2,
    bottom: 1 - (1 - bhFrac) / 2,
  };
}

function overlap1D(aMin, aMax, bMin, bMax) {
  return Math.max(0, Math.min(aMax, bMax) - Math.max(aMin, bMin));
}

// Position-independent "croppability ceiling": the BEST body retention and card
// coverage achievable by any 3:4 crop window of this image, given only the
// person's height/area (no bbox position). This is the right signal before
// auto-crop placement exists — it asks "can a good crop keep the whole body and
// fill the card?" rather than "does the naive centered crop?".
//
//   - Horizontal-crop images (wider than 3:4): full height is always keepable, so
//     retained_height ceiling is 1.0.
//   - Vertical-crop images (taller than 3:4): the window is shorter than the image,
//     so if the person is taller than that window, even a perfect crop must cut
//     head OR feet — retained_height ceiling = windowHeight / personHeight < 1.
// --- Auto-crop solver -------------------------------------------------------
//
// Given the person's bounding box in the source image, choose the crop that puts
// the WHOLE body in the 3:4 card if it fits, else keeps as much as possible
// (head prioritized), while making the body fill as much of the card as possible.
//
// Output is the live-site crop_spec contract (object-fit: cover + object-position
// + transform: scale(zoom), zoom in [1, MAX_ZOOM]); see index.html applyCropSpec.
// Under that model the visible window is, for zoom s:
//   size   = (coverW/s, coverH/s)              // scale is about the box centre
//   centre = ((1-coverW)*X/100 + coverW/2,     // object-position sets the centre
//             (1-coverH)*Y/100 + coverH/2)     // only the overflow axis can move
// so the reachable window centre is fixed to [coverDim/2, 1-coverDim/2] per axis
// and zoom only shrinks the window about that centre.

// Auto-crop renders as an explicit crop window (not object-position + capped
// scale), so zoom is bounded by source resolution rather than a fixed 1.6: we
// tighten onto the subject but keep enough source pixels for a sharp card.
export const MAX_AUTO_ZOOM = 6; // absolute sanity cap
const MIN_CROP_SHORT_PX = 320; // keep at least this many source px in the crop's short side
// Leave a little breathing room so the subject isn't edge-to-edge in the card.
const SUBJECT_MARGIN = 0.06;

function normalizePersonBox(personBox) {
  if (!personBox) return null;
  let left;
  let top;
  let width;
  let height;
  if (personBox.widthPct != null || personBox.wPct != null) {
    width = (personBox.widthPct ?? personBox.wPct) / 100;
    height = (personBox.heightPct ?? personBox.hPct) / 100;
    left = (personBox.leftPct ?? personBox.xPct ?? 0) / 100;
    top = (personBox.topPct ?? personBox.yPct ?? 0) / 100;
  } else if (personBox.x2 != null && personBox.x2 > 1.5) {
    // Pixel xyxy; needs imgWidth/imgHeight on the box.
    const w = personBox.imgWidth;
    const h = personBox.imgHeight;
    if (!w || !h) return null;
    left = personBox.x1 / w;
    top = personBox.y1 / h;
    width = (personBox.x2 - personBox.x1) / w;
    height = (personBox.y2 - personBox.y1) / h;
  } else {
    // Fractional fields.
    left = personBox.left ?? personBox.x1 ?? 0;
    top = personBox.top ?? personBox.y1 ?? 0;
    width = personBox.width ?? (personBox.x2 != null ? personBox.x2 - (personBox.x1 ?? 0) : null);
    height = personBox.height ?? (personBox.y2 != null ? personBox.y2 - (personBox.y1 ?? 0) : null);
  }
  if (width == null || height == null) return null;
  left = clamp01(left);
  top = clamp01(top);
  width = clamp01(width);
  height = clamp01(height);
  if (!width || !height) return null;
  return { left, top, width, height, cx: left + width / 2, cy: top + height / 2 };
}

// Solve object-position for a desired window centre on one axis.
//   centre = (1 - coverDim) * pos + coverDim/2,  pos in [0,1]
// Returns the clamped 0..100 percentage (50 when the axis can't move).
function positionForCenter(desiredCenter, coverDim) {
  const range = 1 - coverDim;
  if (range <= 1e-9) return 50;
  return Math.min(100, Math.max(0, ((desiredCenter - coverDim / 2) / range) * 100));
}

export function solveAutoCrop({
  imgWidth,
  imgHeight,
  personBox,
  priorityRegion = null, // { top, bottom } image fractions — garment band to keep when the body can't fit
  cardAspect = CARD_ASPECT,
  headBias = 0.12,
} = {}) {
  if (!imgWidth || !imgHeight) return null;
  const person = normalizePersonBox(personBox);
  if (!person) return null;
  const imageAspect = imgWidth / imgHeight;
  let coverW;
  let coverH;
  if (imageAspect > cardAspect) {
    coverH = 1;
    coverW = cardAspect / imageAspect;
  } else {
    coverW = 1;
    coverH = imageAspect / cardAspect;
  }
  const k = coverW / coverH; // window width/height ratio in image fractions

  // Resolution-aware zoom cap: don't shrink the crop window below MIN_CROP_SHORT_PX
  // source pixels on its short side, so the card stays sharp.
  const maxZoomRes = Math.min(coverW * imgWidth, coverH * imgHeight) / MIN_CROP_SHORT_PX;
  const maxZoom = Math.max(1, Math.min(MAX_AUTO_ZOOM, maxZoomRes));

  // Realised crop window for a given zoom, centred on the target and clamped to the
  // image edges. Because auto-crop renders an explicit window (not object-position),
  // the window can sit anywhere in the image — no centre-lock on square/3:4 images.
  const realize = (targetBox, s, desiredCyOverride = null) => {
    const winW = coverW / s;
    const winH = coverH / s;
    const tcx = targetBox.left + targetBox.width / 2;
    const tcy = desiredCyOverride != null ? desiredCyOverride : targetBox.top + targetBox.height / 2;
    const realCx = Math.min(1 - winW / 2, Math.max(winW / 2, tcx));
    const realCy = Math.min(1 - winH / 2, Math.max(winH / 2, tcy));
    const left = realCx - winW / 2;
    const top = realCy - winH / 2;
    // Crop-window position as background-position-style percentages (0..100).
    const posX = 1 - winW > 1e-9 ? clamp01(left / (1 - winW)) * 100 : 50;
    const posY = 1 - winH > 1e-9 ? clamp01(top / (1 - winH)) * 100 : 50;
    const tW = overlap1D(targetBox.left, targetBox.left + targetBox.width, left, left + winW);
    const tH = overlap1D(targetBox.top, targetBox.top + targetBox.height, top, top + winH);
    const pW = overlap1D(person.left, person.left + person.width, left, left + winW);
    const pH = overlap1D(person.top, person.top + person.height, top, top + winH);
    return {
      s,
      posX,
      posY,
      winW,
      winH,
      left,
      top,
      targetRetainedWidth: targetBox.width ? clamp01(tW / targetBox.width) : 1,
      targetRetainedHeight: targetBox.height ? clamp01(tH / targetBox.height) : 1,
      personRetainedWidth: person.width ? clamp01(pW / person.width) : 0,
      personRetainedHeight: person.height ? clamp01(pH / person.height) : 0,
      cardCoverage: winW * winH ? clamp01((pW * pH) / (winW * winH)) : 0,
    };
  };

  const containsTarget = (r) => r.targetRetainedHeight >= 0.999 && r.targetRetainedWidth >= 0.999;

  // Largest zoom (max fill) that fully contains targetBox. Containment is monotonic
  // in zoom, so scan downward and take the first that fits; if none fit, centre on
  // the target at zoom 1 (loses equal amounts off each end).
  const bestContain = (targetBox) => {
    // Window needed to hold the target plus a little margin so it isn't edge-to-edge.
    const needH = Math.max(targetBox.height, targetBox.width / k) * (1 + 2 * SUBJECT_MARGIN);
    const fitZoom = needH > 0 ? coverH / needH : 1;
    const sMax = Math.min(maxZoom, Math.max(1, fitZoom));
    for (let s = sMax; s > 1 + 1e-9; s -= 0.01) {
      const r = realize(targetBox, s);
      if (containsTarget(r)) return { r, contains: true };
    }
    const atOne = realize(targetBox, 1);
    if (containsTarget(atOne)) return { r: atOne, contains: true };
    // Can't fit the whole target: keep its TOP (e.g. the waistband / neckline of
    // the garment) by aligning the window top to the target top, rather than
    // centring and losing both ends.
    const topAligned = realize(targetBox, 1, targetBox.top + coverH / 2);
    return { r: topAligned, contains: false };
  };

  // Tier 1: try to fit the whole body (and fill the card). Tier 2: if it can't
  // fit, frame the garment region from taxonomy (e.g. keep the whole pair of
  // pants, sacrificing the head). Tier 3 (no taxonomy): keep the head.
  const wholeBody = bestContain(person);
  let chosen;
  let mode;
  if (wholeBody.contains) {
    chosen = wholeBody.r;
    mode = "whole_body";
  } else if (priorityRegion && priorityRegion.bottom > priorityRegion.top) {
    const region = {
      left: person.left,
      width: person.width,
      top: clamp01(priorityRegion.top),
      height: clamp01(priorityRegion.bottom) - clamp01(priorityRegion.top),
    };
    const fit = bestContain(region);
    chosen = fit.r;
    mode = fit.contains ? "garment_priority" : "garment_partial";
  } else {
    // Head-priority fallback: keep the cover window and bias upward.
    const winH = coverH;
    const headTarget = {
      left: person.left,
      width: person.width,
      top: clamp01(person.top + winH / 2 + headBias * winH - winH / 2),
      height: winH,
    };
    chosen = realize(headTarget, 1);
    mode = "head_priority";
  }

  return {
    crop_spec: {
      // Explicit crop window: render the [windowXPct, windowYPct, windowWPct,
      // windowHPct] rectangle of the source image into the 3:4 card. object-position
      // / zoom are the background-position-style equivalents for renderers that
      // prefer them (background-size: zoom*cover).
      mode: "cover-window",
      aspectRatio: "3:4",
      windowXPct: Math.round(Math.max(0, chosen.left) * 10000) / 100,
      windowYPct: Math.round(Math.max(0, chosen.top) * 10000) / 100,
      windowWPct: Math.round(chosen.winW * 10000) / 100,
      windowHPct: Math.round(chosen.winH * 10000) / 100,
      objectPositionXPct: Math.round(chosen.posX * 100) / 100,
      objectPositionYPct: Math.round(chosen.posY * 100) / 100,
      zoom: Math.round(chosen.s * 1000) / 1000,
      rotationDeg: 0,
      source: "auto",
    },
    evidence: {
      mode,
      contains_whole_body: mode === "whole_body",
      retained_height: Math.round(chosen.personRetainedHeight * 1000) / 1000,
      retained_width: Math.round(chosen.personRetainedWidth * 1000) / 1000,
      card_coverage: Math.round(chosen.cardCoverage * 1000) / 1000,
      person_box: person,
      priority_region: priorityRegion ? { top: priorityRegion.top, bottom: priorityRegion.bottom } : null,
      garment_retained: mode.startsWith("garment") ? Math.round(chosen.targetRetainedHeight * 1000) / 1000 : null,
      cover_window: { wFrac: coverW, hFrac: coverH },
      // Realised visible window in image fractions (for overlaying on the original).
      window: {
        left: Math.max(0, Math.round(chosen.left * 10000) / 10000),
        top: Math.max(0, Math.round(chosen.top * 10000) / 10000),
        width: Math.round(chosen.winW * 10000) / 10000,
        height: Math.round(chosen.winH * 10000) / 10000,
      },
    },
  };
}

export function estimateBestAchievableCrop({ imgWidth, imgHeight, heightPct, areaPct, cardAspect = CARD_ASPECT }) {
  if (!imgWidth || !imgHeight) return null;
  const imageAspect = imgWidth / imgHeight;
  let wFrac;
  let hFrac;
  if (imageAspect > cardAspect) {
    hFrac = 1;
    wFrac = cardAspect / imageAspect;
  } else {
    wFrac = 1;
    hFrac = imageAspect / cardAspect;
  }
  const personH = clamp01(heightPct);
  if (!personH) return null;
  const personW = clamp01(areaPct / personH);
  const visH = Math.min(personH, hFrac); // optimal placement covers as much body as fits
  const visW = Math.min(personW, wFrac);
  const windowArea = wFrac * hFrac;
  return {
    window: { wFrac, hFrac },
    person: { bwFrac: personW, bhFrac: personH },
    retainedHeight: clamp01(visH / personH),
    retainedWidth: personW ? clamp01(visW / personW) : 0,
    cardCoverage: windowArea ? clamp01((visH * visW) / windowArea) : 0,
    person_center_assumed: false,
    best_achievable: true,
  };
}

// How much of the body survives the crop, and how much of the card it fills.
// Returns:
//   retainedHeight / retainedWidth — fraction of the person's bbox height/width
//     still inside the window (1 = fully kept; <1 = head/feet or sides cut off).
//   cardCoverage — fraction of the card area occupied by the visible body.
export function estimateBodyAfterCrop({ imgWidth, imgHeight, heightPct, areaPct, cropSpec = null, cardAspect = CARD_ASPECT }) {
  // Resolve via cropWindowFractions so the explicit cover-window model (windowXPct
  // etc.) is honored, not just object-position+zoom.
  const wf = cropWindowFractions(imgWidth, imgHeight, cropSpec, cardAspect);
  const person = personBoxFromMetrics(heightPct, areaPct);
  if (!wf || !person) return null;
  const window = { xFrac: wf.leftFrac, yFrac: wf.topFrac, wFrac: wf.widthFrac, hFrac: wf.heightFrac, mode: wf.mode };
  const winRight = window.xFrac + window.wFrac;
  const winBottom = window.yFrac + window.hFrac;
  const overlapW = overlap1D(person.left, person.right, window.xFrac, winRight);
  const overlapH = overlap1D(person.top, person.bottom, window.yFrac, winBottom);
  const overlapArea = overlapW * overlapH;
  const windowArea = window.wFrac * window.hFrac;
  return {
    window,
    person: { bwFrac: person.bwFrac, bhFrac: person.bhFrac },
    retainedWidth: person.bwFrac ? clamp01(overlapW / person.bwFrac) : 0,
    retainedHeight: person.bhFrac ? clamp01(overlapH / person.bhFrac) : 0,
    cardCoverage: windowArea ? clamp01(overlapArea / windowArea) : 0,
    person_center_assumed: true,
  };
}
