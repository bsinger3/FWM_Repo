#!/usr/bin/env node

// Writes auto-crop crop_spec values into dev public.images. Dry-run by default
// (local report only); --apply writes to dev Supabase behind the dev guard, the
// explicit write flag, and a passed crops verification report.
//
// Input is the detection ndjson from scripts/detect_person_boxes.py. Crops are
// decided by the shared lib (scripts/lib/detection-crop.mjs) so what gets written
// is exactly what the review dashboard shows. Per the human decision, only
// whole_body / garment_priority / garment_partial modes are written; head_priority
// (no usable garment region) and no-person / fetch-error rows are skipped.

import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  callSupabaseRest,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "./lib/postgres-client.mjs";
import { decideCrop, cropSpecForStorage, WRITABLE_MODES } from "./lib/detection-crop.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const inputPath = parseArg("input", "/tmp/crop_bboxes.ndjson");
const catalogPathArg = parseArg("catalog", null);
const verifiedReportPath = parseArg("verified-report");
const limit = Math.max(0, Number(parseArg("limit", "0")) || 0);
const CROP_MODEL_VERSION = "auto_crop_garment_aware_v1";
const WRITE_CONCURRENCY = Math.max(1, Number(parseArg("concurrency", "12")) || 12);

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function ts() {
  return new Date().toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

// Run an async worker over items with bounded concurrency; calls onProgress(done)
// every 200 completions.
async function runPool(items, worker, concurrency, onProgress) {
  let next = 0;
  let done = 0;
  async function lane() {
    while (next < items.length) {
      const item = items[next++];
      await worker(item);
      done += 1;
      if (onProgress && done % 200 === 0) onProgress(done);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, lane));
}

// Ids that already have an auto (cover-window) crop, so a re-run resumes instead
// of rewriting. Paginated through PostgREST.
async function fetchExistingAutoCropIds(guard) {
  const ids = new Set();
  const page = 1000;
  let offset = 0;
  for (;;) {
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "images",
      method: "GET",
      searchParams: { select: "id", "crop_spec->>mode": "eq.cover-window", order: "id", limit: String(page), offset: String(offset) },
    });
    if (!Array.isArray(data) || data.length === 0) break;
    for (const r of data) ids.add(r.id);
    if (data.length < page) break;
    offset += page;
  }
  return ids;
}

function runPsql(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...connection.env }, maxBuffer: 1024 * 1024 * 50 },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

// clothing_type_id -> mother_category_id. Prefer an explicit --catalog file, else
// build it from dev staging.clothing_type_tags, else fall back to a tmp cache.
async function loadCatalog() {
  if (catalogPathArg) return JSON.parse(await readFile(catalogPathArg, "utf8"));
  try {
    assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);
    const out = runPsql(
      process.env.DEV_DATABASE_URL,
      "select coalesce(jsonb_object_agg(id, mother_category_id), '{}'::jsonb) from staging.clothing_type_tags where mother_category_id is not null;",
    );
    return JSON.parse(out.trim() || "{}");
  } catch (error) {
    console.warn(`Could not build catalog from dev (${error.message || error}); trying /tmp/clothing_catalog.json`);
    try {
      return JSON.parse(await readFile("/tmp/clothing_catalog.json", "utf8"));
    } catch {
      console.warn("No clothing catalog available — only whole_body crops will be written.");
      return {};
    }
  }
}

async function requirePassedVerificationReport() {
  if (!verifiedReportPath) {
    throw new Error(
      "Apply mode requires --verified-report=/absolute/path/dev_refresh_report_verify_crops_*.json from a passed verification.",
    );
  }
  const report = JSON.parse(await readFile(path.resolve(verifiedReportPath), "utf8"));
  if (report.report_type !== "crops" || report.passed !== true) {
    throw new Error(`Verification report did not pass for crops: ${verifiedReportPath}`);
  }
  return report;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Crop backfill guard" });

  const generatedAt = new Date().toISOString();
  const catalog = await loadCatalog();
  const raw = await readFile(inputPath, "utf8");
  let recs = raw.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => JSON.parse(l));
  if (limit) recs = recs.slice(0, limit);

  const byMode = {};
  const skips = {};
  const plannedWrites = [];
  for (const rec of recs) {
    const decision = decideCrop(rec, { catalog });
    if (decision.skip) {
      skips[decision.skip] = (skips[decision.skip] || 0) + 1;
      continue;
    }
    const mode = decision.crop.evidence.mode;
    byMode[mode] = (byMode[mode] || 0) + 1;
    if (!WRITABLE_MODES.has(mode)) {
      skips[`mode_${mode}`] = (skips[`mode_${mode}`] || 0) + 1;
      continue;
    }
    plannedWrites.push({
      id: rec.id,
      url: rec.url,
      mode,
      clothing_type_id: decision.clothingType,
      mother_category: decision.motherCategory,
      crop_spec: cropSpecForStorage(decision.crop, { modelVersion: CROP_MODEL_VERSION, scoredAt: generatedAt }),
      retained_height: decision.crop.evidence.retained_height,
      card_coverage: decision.crop.evidence.card_coverage,
    });
  }

  let appliedRows = 0;
  let alreadyPresent = 0;
  if (apply) {
    requireExplicitWriteFlag();
    await requirePassedVerificationReport();
    // Resume: skip rows that already carry an auto (cover-window) crop, so a
    // re-run after an interruption continues instead of re-writing everything.
    const done = await fetchExistingAutoCropIds(guard);
    const toWrite = plannedWrites.filter((w) => !done.has(w.id));
    alreadyPresent = plannedWrites.length - toWrite.length;
    console.log(`[${ts()}] ${alreadyPresent} already auto-cropped; writing ${toWrite.length} (concurrency ${WRITE_CONCURRENCY})`);
    const t0 = Date.now();
    await runPool(
      toWrite,
      async (w) => {
        await callSupabaseRest({
          supabaseUrl: guard.supabaseUrl,
          serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
          path: "images",
          method: "PATCH",
          searchParams: { id: `eq.${w.id}` },
          body: { crop_spec: w.crop_spec },
          prefer: "return=minimal",
        });
      },
      WRITE_CONCURRENCY,
      (n) => {
        const rate = Math.round(n / Math.max(1, (Date.now() - t0) / 1000));
        console.log(`[${ts()}] applied ${n}/${toWrite.length} (${rate}/s)`);
      },
    );
    appliedRows = toWrite.length;
    console.log(`[${ts()}] done: wrote ${appliedRows}, skipped ${alreadyPresent} already present`);
  }

  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(
    reportsDir,
    `dev_image_crop_backfill_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`,
  );
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    crop_model_version: CROP_MODEL_VERSION,
    input: inputPath,
    skip_rule: "write iff mode in {whole_body, garment_priority, garment_partial}",
    totals: {
      detections: recs.length,
      planned_writes: plannedWrites.length,
      skipped: recs.length - plannedWrites.length,
      applied_rows: apply ? appliedRows : 0,
      already_present_skipped: apply ? alreadyPresent : 0,
    },
    by_mode: byMode,
    skips,
    catalog_size: Object.keys(catalog).length,
    sample_writes: plannedWrites.slice(0, 30),
    planned_writes: plannedWrites,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote crop backfill report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Detections: ${recs.length} | Planned writes: ${plannedWrites.length} | Skipped: ${report.totals.skipped}`);
  console.log(`By mode: ${JSON.stringify(byMode)}`);
  console.log(`Skips: ${JSON.stringify(skips)}`);
  if (apply) console.log(`Applied ${appliedRows} crop_spec writes to dev.`);
  else console.log("Dry-run only. No Supabase rows were written. Review, verify, then rerun with --apply.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
