#!/usr/bin/env node
// Turn the extraction-audit re-extraction report into a measurement-override map
// the approved-images loader can consume, so corrected (current-regex) values
// flow into dev images WITHOUT mutating the 326 review workbooks.
//
// Reads : <FWM_Data>/_reports/extraction_audit/reextraction.json
//           (per-comment old/new/final from the improved extract_measurements)
// Writes: <FWM_Data>/_reports/extraction_audit/measurement_overrides.json
//           { built_at, source, count, overrides: { <commentId>: {<image columns>} } }
//
// The loader joins by commentId(user_comment) — the same FNV id the audit uses —
// so every approved image row sharing a corrected comment gets the fix.
//
// Usage: node scripts/build-measurement-overrides.mjs

import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const auditDir = path.join(fwmDataDir(repoRoot), "_reports", "extraction_audit");
const inPath = path.join(auditDir, "reextraction.json");
const outPath = path.join(auditDir, "measurement_overrides.json");

// final (dashboard) field -> public.images column.
// weeks_pregnant is intentionally omitted: the loader re-parses pregnancy from the
// comment itself. age_years_display IS carried here and written by the measurement
// backfill (the loader's RPC still doesn't accept age, but the backfill does).
const COLUMN_MAP = [
  ["heightIn", "height_in_display"],
  ["weightLbs", "weight_lbs_display"],
  ["waistIn", "waist_in"],
  ["hipsIn", "hips_in_display"],
  ["bustIn", "bust_in_display"],
  ["braBandIn", "bra_band_in_display"],
  ["cupSize", "cupsize_display"],
  ["inseamIn", "inseam_inches_display"],
  ["ageYears", "age_years_display"],
];

const report = JSON.parse(await readFile(inPath, "utf8"));
const overrides = {};
let count = 0;
for (const row of report.rows) {
  if (!row.id) continue;
  const final = row.final || {};
  const cols = {};
  for (const [k, col] of COLUMN_MAP) cols[col] = String(final[k] ?? "");
  overrides[row.id] = cols;
  count += 1;
}

await mkdir(auditDir, { recursive: true });
await writeFile(
  outPath,
  JSON.stringify(
    {
      built_at: new Date().toISOString(),
      source: path.basename(inPath),
      source_rerun_at: report.rerun_at,
      extractor: report.extractor,
      note: "Loader joins by commentId(user_comment); empty string clears a column.",
      count,
      overrides,
    },
    null,
    2,
  ),
);
console.log(`Wrote ${count.toLocaleString()} comment overrides -> ${outPath}`);
