// Deterministic "lighting quality" scoring over the pixel stats from
// scripts/lib/pixel-stats.mjs. This is the SINGLE SOURCE OF TRUTH for lighting:
// both the prettiness scorer (score-dev-image-prettiness.mjs) and the lighting
// label/calibration dashboard import from here, so recalibrating thresholds in
// one place updates everything.
//
// Four sub-signals, each 0..1, weighted into one lighting score:
//   - exposure:   penalize crushed shadows + blown highlights (clipped pixels)
//   - brightness: reward a bright, "light" frame from mean luma
//   - contrast:   reward healthy contrast, penalize flat/foggy and harsh extremes
//   - cast:       penalize a strong global color cast (poor white balance)
// All thresholds are calibration knobs — tune them against human lighting labels.

// Weights recalibrated 2026-06-25 against 47 human lighting labels (44 "bad"
// false-highs + 3 good/great). The labels showed exposure and contrast were near
// 1.0 for almost every image (non-discriminating) and were inflating bad photos to
// ~0.82; brightness was the only signal that tracked the human judgement. So
// brightness now dominates and exposure/contrast are trimmed. This lifted bad-vs-good
// separation from 0.13 to 0.29 while keeping the good/great anchors at 0.93-0.97.
export const LIGHTING_WEIGHTS = { exposure: 0.22, brightness: 0.6, contrast: 0.06, cast: 0.12 };

// Exposure: ~15% clipped pixels (shadow + highlight) -> 0.
export const EXPOSURE_CLIP_ZERO = 0.15;

// Color cast: cast >= this -> 0 (strong tint).
export const CAST_ZERO = 0.25;

function clamp01(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
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

// Penalize crushed shadows + blown highlights.
export function exposureScore(stats) {
  const clipped = stats.clipped_shadow_frac + stats.clipped_highlight_frac;
  return clamp01(1 - clipped / EXPOSURE_CLIP_ZERO);
}

// Reward a bright, "light" frame. Recalibrated 2026-06-25 against human labels:
// the "bad" lighting examples skewed dim (median luma ~97) while good/great sat at
// luma ~118-133, so the dim end now falls off much harder and the sweet spot
// centers where the good photos live (~113-170). Genuinely blown-out frames are
// still caught by exposureScore, so this only softly rolls off the very-bright end.
export function brightnessScore(mean) {
  if (mean >= 113 && mean <= 170) return 1; // bright + airy: where good/great labels land
  if (mean >= 98 && mean < 113) return 0.62; // mid: starting to feel flat/dim
  if (mean > 170 && mean <= 205) return 0.85; // bright, edging toward washed out
  if (mean >= 82 && mean < 98) return 0.4; // dim
  if (mean > 205 && mean <= 225) return 0.6; // quite bright
  if (mean >= 66 && mean < 82) return 0.25; // quite dim
  if (mean > 225) return 0.4; // near-white / overexposed (exposureScore also bites)
  if (mean >= 50 && mean < 66) return 0.13; // dark
  return 0.06; // very dark
}

// Reward healthy contrast; penalize flat/foggy and harsh extremes. Narrowed
// 2026-06-25: the old 35-75 plateau returned 1.0 for ~every labeled image
// (including all 44 "bad" ones), so it carried no signal. Tighter ideal band +
// low weight (0.06) so it nudges rather than inflates.
export function contrastScore(std) {
  if (std >= 45 && std <= 68) return 1;
  if (std >= 35 && std < 45) return 0.85;
  if (std > 68 && std <= 85) return 0.8;
  if (std >= 25 && std < 35) return 0.6;
  if (std > 85 && std <= 105) return 0.5;
  return 0.3;
}

// Penalize a strong global color cast (poor white balance).
export function castScore(cast) {
  return clamp01(1 - cast / CAST_ZERO);
}

export function lightingScore(stats) {
  if (!stats) return null;
  return weightedMean([
    [exposureScore(stats), LIGHTING_WEIGHTS.exposure],
    [brightnessScore(stats.mean_luma), LIGHTING_WEIGHTS.brightness],
    [contrastScore(stats.contrast_std), LIGHTING_WEIGHTS.contrast],
    [castScore(stats.color_cast), LIGHTING_WEIGHTS.cast],
  ]);
}

// Full breakdown for the calibration dashboard: the overall lighting score, each
// sub-score, and the raw pixel measurements that drive them. Returns null when
// stats are unavailable.
export function lightingBreakdown(stats) {
  if (!stats) return null;
  return {
    lighting: lightingScore(stats),
    exposure: exposureScore(stats),
    brightness: brightnessScore(stats.mean_luma),
    contrast: contrastScore(stats.contrast_std),
    cast: castScore(stats.color_cast),
    raw: {
      mean_luma: stats.mean_luma,
      contrast_std: stats.contrast_std,
      color_cast: stats.color_cast,
      clipped_shadow_frac: stats.clipped_shadow_frac,
      clipped_highlight_frac: stats.clipped_highlight_frac,
    },
  };
}
