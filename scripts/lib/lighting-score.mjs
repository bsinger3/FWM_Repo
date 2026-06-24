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

export const LIGHTING_WEIGHTS = { exposure: 0.35, brightness: 0.4, contrast: 0.15, cast: 0.1 };

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

// Reward a bright, "light" frame. Sweet spot leans to the upper-mid range; dark
// frames are penalized harder than slightly-bright ones; genuinely blown-out
// frames are still caught by exposureScore, so this only softly rolls off the
// very-bright end.
export function brightnessScore(mean) {
  if (mean >= 120 && mean <= 195) return 1; // bright + airy: the target
  if (mean >= 100 && mean < 120) return 0.9; // pleasantly lit
  if (mean > 195 && mean <= 215) return 0.85; // bright, edging toward washed out
  if (mean >= 80 && mean < 100) return 0.7; // a bit dim
  if (mean > 215 && mean <= 230) return 0.6; // quite bright
  if (mean >= 60 && mean < 80) return 0.45; // dim
  if (mean > 230) return 0.4; // near-white / overexposed (exposureScore also bites)
  if (mean >= 45 && mean < 60) return 0.3; // dark
  return 0.15; // very dark
}

// Reward healthy contrast; penalize flat/foggy and harsh extremes.
export function contrastScore(std) {
  if (std >= 35 && std <= 75) return 1;
  if (std >= 25 && std < 35) return 0.8;
  if (std > 75 && std <= 90) return 0.8;
  if (std >= 15 && std < 25) return 0.5;
  if (std > 90 && std <= 110) return 0.5;
  return 0.25;
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
