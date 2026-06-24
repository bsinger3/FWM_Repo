// Deterministic pixel statistics for the prettiness scorer's technical bucket
// (plan §12, Phase 2 proxy). Decodes an image to a tiny thumbnail and computes
// luminance/exposure/contrast/color-cast stats, a Hasler-Susstrunk colorfulness
// measure, plus a WHOLE-FRAME edge-busyness proxy for background clutter.
//
// IMPORTANT: edge_busyness is whole-frame. With no person bbox position in the
// CV checkpoint we cannot isolate the background, so a busy outfit/pattern reads
// as "clutter" too. It is a coarse stopgap until detection is re-run with a
// person mask; weight it low. No ML here — pure arithmetic over decoded pixels.

import sharp from "sharp";

const THUMB_PX = 96; // stats don't need resolution; small = fast + stable.
const SHADOW_CLIP = 4; // luma <= this counts as crushed shadow
const HIGHLIGHT_CLIP = 251; // luma >= this counts as blown highlight
const EDGE_THRESHOLD = 48; // Sobel gradient magnitude (0..~1020) counted as an edge

// Rec. 709 luma weights.
function luma(r, g, b) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// Decode -> (optional crop) -> downsample -> raw RGB. Throws if the buffer can't
// be decoded; the caller treats a throw as "stats unavailable" (component null).
// `crop` is a fractional rect of the source { leftFrac, topFrac, widthFrac,
// heightFrac } — pass it to measure the CARD window (post-autocrop) rather than
// the full source image.
export async function computePixelStats(buffer, { size = THUMB_PX, crop = null } = {}) {
  let pipeline = sharp(buffer);
  if (crop) {
    const meta = await sharp(buffer).metadata();
    const W = meta.width;
    const H = meta.height;
    if (W && H) {
      const left = Math.min(W - 1, Math.max(0, Math.round(crop.leftFrac * W)));
      const top = Math.min(H - 1, Math.max(0, Math.round(crop.topFrac * H)));
      const width = Math.max(1, Math.min(W - left, Math.round(crop.widthFrac * W)));
      const height = Math.max(1, Math.min(H - top, Math.round(crop.heightFrac * H)));
      pipeline = sharp(buffer).extract({ left, top, width, height });
    }
  }
  const { data, info } = await pipeline
    .resize(size, size, { fit: "inside", withoutEnlargement: false })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  return statsFromRaw(data, info.width, info.height, info.channels);
}

// Pure: raw interleaved channel bytes -> stats. Exported for unit testing.
export function statsFromRaw(data, width, height, channels = 3) {
  const pixelCount = width * height;
  if (!pixelCount) return null;

  const lumaGrid = new Float64Array(pixelCount);
  let sumLuma = 0;
  let sumLumaSq = 0;
  let sumR = 0;
  let sumG = 0;
  let sumB = 0;
  let shadowClipped = 0;
  let highlightClipped = 0;
  // Hasler-Susstrunk opponent channels for colorfulness: rg = R - G,
  // yb = 0.5(R + G) - B. Accumulate means + variances in one pass.
  let sumRG = 0;
  let sumRGSq = 0;
  let sumYB = 0;
  let sumYBSq = 0;

  for (let i = 0; i < pixelCount; i += 1) {
    const o = i * channels;
    const r = data[o];
    const g = data[o + 1];
    const b = data[o + 2];
    const y = luma(r, g, b);
    lumaGrid[i] = y;
    sumLuma += y;
    sumLumaSq += y * y;
    sumR += r;
    sumG += g;
    sumB += b;
    const rg = r - g;
    const yb = 0.5 * (r + g) - b;
    sumRG += rg;
    sumRGSq += rg * rg;
    sumYB += yb;
    sumYBSq += yb * yb;
    if (y <= SHADOW_CLIP) shadowClipped += 1;
    if (y >= HIGHLIGHT_CLIP) highlightClipped += 1;
  }

  const meanLuma = sumLuma / pixelCount;
  const variance = Math.max(0, sumLumaSq / pixelCount - meanLuma * meanLuma);
  const contrastStd = Math.sqrt(variance);

  const meanR = sumR / pixelCount;
  const meanG = sumG / pixelCount;
  const meanB = sumB / pixelCount;
  const grayMean = (meanR + meanG + meanB) / 3;
  const colorCast =
    Math.max(Math.abs(meanR - grayMean), Math.abs(meanG - grayMean), Math.abs(meanB - grayMean)) / 255;

  // Colorfulness (Hasler-Susstrunk 2003): sqrt(std_rg^2 + std_yb^2)
  // + 0.3 * sqrt(mean_rg^2 + mean_yb^2). Higher = more vivid/varied color.
  // ~0 for grayscale; ~60-110 for vivid frames on the 0..255 channel scale.
  const meanRG = sumRG / pixelCount;
  const meanYB = sumYB / pixelCount;
  const stdRG = Math.sqrt(Math.max(0, sumRGSq / pixelCount - meanRG * meanRG));
  const stdYB = Math.sqrt(Math.max(0, sumYBSq / pixelCount - meanYB * meanYB));
  const colorfulness =
    Math.sqrt(stdRG * stdRG + stdYB * stdYB) + 0.3 * Math.sqrt(meanRG * meanRG + meanYB * meanYB);

  return {
    width,
    height,
    mean_luma: meanLuma,
    contrast_std: contrastStd,
    clipped_shadow_frac: shadowClipped / pixelCount,
    clipped_highlight_frac: highlightClipped / pixelCount,
    color_cast: colorCast,
    colorfulness,
    edge_busyness: edgeBusyness(lumaGrid, width, height),
  };
}

// Fraction of interior pixels whose Sobel gradient magnitude exceeds the edge
// threshold. High => busy/textured frame.
function edgeBusyness(lumaGrid, width, height) {
  if (width < 3 || height < 3) return 0;
  let edges = 0;
  let counted = 0;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const idx = y * width + x;
      const tl = lumaGrid[idx - width - 1];
      const tc = lumaGrid[idx - width];
      const tr = lumaGrid[idx - width + 1];
      const ml = lumaGrid[idx - 1];
      const mr = lumaGrid[idx + 1];
      const bl = lumaGrid[idx + width - 1];
      const bc = lumaGrid[idx + width];
      const br = lumaGrid[idx + width + 1];
      const gx = tr + 2 * mr + br - (tl + 2 * ml + bl);
      const gy = bl + 2 * bc + br - (tl + 2 * tc + tr);
      const mag = Math.sqrt(gx * gx + gy * gy);
      if (mag >= EDGE_THRESHOLD) edges += 1;
      counted += 1;
    }
  }
  return counted ? edges / counted : 0;
}
