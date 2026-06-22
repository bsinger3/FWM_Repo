// Builds an index of YOLO/pose CV metrics from the CV-gate checkpoint CSVs,
// keyed by review_row_key, so loaders/backfills/scorers can attach body signals
// to dev images without re-running CV. The raw 65-part CSV set is ~395MB, so the
// parsed index is cached as compact JSON under FWM_Data and only rebuilt when the
// caller passes { rebuild: true } or the cache is missing.

import { createReadStream } from "node:fs";
import { mkdir, readFile, writeFile, readdir, stat } from "node:fs/promises";
import { createInterface } from "node:readline";
import path from "node:path";
import { fwmDataDir } from "../../tools/image-review-dashboard/paths.mjs";

const CHECKPOINT_SUBDIR = path.join(
  "03_cv_annotated_pending_human_review",
  "partial_170000_rows_cv_gated",
  "cv_gate_checkpoint_parts",
);
const CACHE_SUBPATH = path.join("_cache", "workbook_cv_index.json");
const INDEX_VERSION = "workbook_cv_index_v1";

const CV_COLUMNS = {
  review_row_key: "review_row_key",
  person_count: "person_count_yolo_detect",
  height_pct: "main_person_height_pct_yolo_detect",
  area_pct: "main_person_bbox_area_pct_yolo_detect",
  body_coverage_pose: "body_coverage_score_yolo_pose",
  has_face: "has_face_yunet",
};

// Minimal quote-aware CSV row splitter (handles embedded commas in quoted
// fields, e.g. URLs/titles). Embedded newlines inside quotes are not expected in
// these checkpoints and are not handled.
function splitCsvLine(line) {
  const fields = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          current += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        current += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      fields.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

function toNumberOrNull(value) {
  if (value === undefined || value === null || value === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function toBoolOrNull(value) {
  if (value === undefined || value === null || value === "") return null;
  const lower = String(value).trim().toLowerCase();
  if (["true", "1", "yes", "t"].includes(lower)) return true;
  if (["false", "0", "no", "f"].includes(lower)) return false;
  return null;
}

function normalizeRow(record) {
  // body_coverage_score_yolo_pose is on a 0..100 scale in the checkpoints.
  const poseRaw = toNumberOrNull(record.body_coverage_pose);
  return {
    person_count: toNumberOrNull(record.person_count),
    height_pct: toNumberOrNull(record.height_pct),
    area_pct: toNumberOrNull(record.area_pct),
    body_coverage_pose: poseRaw === null ? null : Math.max(0, Math.min(1, poseRaw / 100)),
    has_face: toBoolOrNull(record.has_face),
  };
}

async function scanCheckpoints(checkpointDir) {
  const files = (await readdir(checkpointDir))
    .filter((name) => name.endsWith(".csv"))
    .sort();
  const index = {};
  let scannedRows = 0;
  for (const file of files) {
    const filePath = path.join(checkpointDir, file);
    const rl = createInterface({ input: createReadStream(filePath, "utf8"), crlfDelay: Infinity });
    let headerIndex = null;
    for await (const line of rl) {
      if (headerIndex === null) {
        const headers = splitCsvLine(line);
        headerIndex = {};
        for (const [key, columnName] of Object.entries(CV_COLUMNS)) {
          headerIndex[key] = headers.indexOf(columnName);
        }
        continue;
      }
      if (!line) continue;
      const fields = splitCsvLine(line);
      const key = fields[headerIndex.review_row_key];
      if (!key) continue;
      scannedRows += 1;
      const record = {};
      for (const fieldKey of Object.keys(CV_COLUMNS)) {
        const col = headerIndex[fieldKey];
        record[fieldKey] = col >= 0 ? fields[col] : "";
      }
      // Last write wins if a key repeats across parts.
      index[key] = normalizeRow(record);
    }
  }
  return { index, scannedRows, fileCount: files.length };
}

// Returns a Map-like object: { byKey, meta }. byKey is a plain object keyed by
// review_row_key -> { person_count, height_pct, area_pct, body_coverage_pose, has_face }.
export async function loadWorkbookCvIndex({ cwd = process.cwd(), rebuild = false } = {}) {
  const dataDir = fwmDataDir(cwd);
  const cachePath = path.join(dataDir, CACHE_SUBPATH);
  const checkpointDir = path.join(dataDir, CHECKPOINT_SUBDIR);

  if (!rebuild) {
    try {
      const cached = JSON.parse(await readFile(cachePath, "utf8"));
      if (cached.version === INDEX_VERSION && cached.byKey) {
        return { byKey: cached.byKey, meta: { ...cached.meta, cache_hit: true, cache_path: cachePath } };
      }
    } catch {
      // Fall through to rebuild.
    }
  }

  await stat(checkpointDir).catch(() => {
    throw new Error(`CV checkpoint directory not found: ${checkpointDir}`);
  });
  const { index, scannedRows, fileCount } = await scanCheckpoints(checkpointDir);
  const meta = {
    version: INDEX_VERSION,
    built_at: new Date().toISOString(),
    checkpoint_dir: checkpointDir,
    file_count: fileCount,
    scanned_rows: scannedRows,
    indexed_keys: Object.keys(index).length,
  };
  await mkdir(path.dirname(cachePath), { recursive: true });
  await writeFile(cachePath, JSON.stringify({ ...meta, byKey: index }) + "\n", "utf8");
  return { byKey: index, meta: { ...meta, cache_hit: false, cache_path: cachePath } };
}
