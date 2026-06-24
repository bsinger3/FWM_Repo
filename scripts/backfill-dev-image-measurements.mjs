#!/usr/bin/env node
// Backfill corrected measurements onto EXISTING dev public.images rows.
//
// Why this exists: the approved-images loader RPC only writes measurement columns
// when it INSERTS a new image. On merge/update of an already-loaded image it
// refreshes crop/pregnancy/linkage only — never the measurement columns. So
// re-running the loader cannot push corrected (current-regex) measurements onto
// the ~31k images that already exist. This script does exactly that, and ONLY
// that: it updates the 8 measurement columns on public.images, nothing else.
//
// Join: each override is keyed by commentId(comment); we match dev images by
// commentId(user_comment) — the same FNV id the audit + loader use.
//
// Dev-only + gated: refuses any non-dev Supabase/DB URL; dry-run unless --apply
// AND FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev are both set.
//
// Usage:
//   node scripts/backfill-dev-image-measurements.mjs            # dry-run (no writes)
//   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
//   node scripts/backfill-dev-image-measurements.mjs --apply    # write to dev

import { spawn } from "node:child_process";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  callSupabaseRest,
  requireExplicitWriteFlag,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs } from "./lib/postgres-client.mjs";
import { commentId } from "../tools/extraction-audit-dashboard/lib/analyze.mjs";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const overridesPath =
  process.argv.find((a) => a.startsWith("--measurement-overrides="))?.split("=")[1] ||
  path.join(fwmDataDir(repoRoot), "_reports", "extraction_audit", "measurement_overrides.json");

// override key (= public.images column) -> sql type for jsonb_to_recordset
const COLUMNS = [
  ["height_in_display", "numeric"],
  ["weight_lbs_display", "numeric"],
  ["waist_in", "numeric"],
  ["hips_in_display", "numeric"],
  ["bust_in_display", "numeric"],
  ["bra_band_in_display", "numeric"],
  ["cupsize_display", "text"],
  ["inseam_inches_display", "numeric"],
  ["age_years_display", "integer"],
];

function toNumberOrNull(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function desiredFromOverride(ov) {
  const out = {};
  for (const [col, type] of COLUMNS) {
    // numeric + integer columns parse to a number (or null); text passes through.
    out[col] = type === "text" ? String(ov[col] ?? "").trim() || null : toNumberOrNull(ov[col]);
  }
  return out;
}

async function fetchAllImages(guard) {
  const rows = [];
  const limit = 1000;
  for (let offset = 0; ; offset += limit) {
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "images",
      searchParams: { select: "id,user_comment", order: "id.asc", limit: String(limit), offset: String(offset) },
    });
    rows.push(...data);
    process.stdout.write(`\r  fetched ${rows.length} image rows…`);
    if (data.length < limit) break;
  }
  process.stdout.write("\n");
  return rows;
}

function runPsqlBatches(databaseUrl, jsonBatches) {
  return new Promise((resolve, reject) => {
    const { args, env } = postgresConnectionArgs(databaseUrl);
    const psql = postgresClientTool("psql");
    const recordset = COLUMNS.map(([c, t]) => `${c} ${t}`).join(", ");
    const proc = spawn(psql, [...args, "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"], {
      env: { ...process.env, ...env },
      stdio: ["pipe", "inherit", "inherit"],
    });
    proc.on("error", reject);
    proc.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`psql exited ${code}`))));
    const setClause = COLUMNS.map(([c]) => `${c} = v.${c}`).join(",\n  ");
    proc.stdin.write("BEGIN;\n");
    for (const batch of jsonBatches) {
      // Dollar-quoted ($fwm$…$fwm$) so the JSON's quotes/commas pass through
      // literally; the payload (uuids, numbers, cup letters) never contains the tag.
      const json = JSON.stringify(batch);
      proc.stdin.write(
        `UPDATE public.images img SET\n  ${setClause}\n` +
          `FROM jsonb_to_recordset($fwm$${json}$fwm$::jsonb) AS v(id uuid, ${recordset})\n` +
          `WHERE img.id = v.id;\n`,
      );
    }
    proc.stdin.write("COMMIT;\n");
    proc.stdin.end();
  });
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot });
  printGuardSummary(guard, { prefix: "Measurement backfill guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const overrides = JSON.parse(await readFile(overridesPath, "utf8")).overrides;
  console.log(`Loaded ${Object.keys(overrides).length.toLocaleString()} comment overrides.`);

  console.log("Fetching dev images (id + comment)…");
  const images = await fetchAllImages(guard);

  // Match each image to its override and compute the desired measurement values.
  const updates = [];
  const fieldFill = Object.fromEntries(COLUMNS.map(([c]) => [c, 0]));
  let matched = 0;
  for (const img of images) {
    const ov = overrides[commentId(img.user_comment)];
    if (!ov) continue;
    matched += 1;
    const desired = desiredFromOverride(ov);
    for (const [c] of COLUMNS) if (desired[c] !== null) fieldFill[c] += 1;
    updates.push({ id: img.id, ...desired });
  }

  console.log(
    `\nMatched ${matched.toLocaleString()} of ${images.length.toLocaleString()} dev images to an override.`,
  );
  console.log("Non-null values to be written per column:");
  for (const [c] of COLUMNS) console.log(`  ${c.padEnd(22)} ${fieldFill[c].toLocaleString()}`);

  // Report (always written; no DB changes for a dry-run).
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports", "extraction_audit");
  await mkdir(reportsDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const reportPath = path.join(reportsDir, `dev_image_measurement_backfill_${stamp}.json`);
  await writeFile(
    reportPath,
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        mode: apply ? "apply" : "dry-run",
        supabase_ref: guard.projectRef,
        overrides_path: overridesPath,
        dev_images_scanned: images.length,
        rows_to_update: updates.length,
        nonnull_per_column: fieldFill,
        samples: updates.slice(0, 20),
      },
      null,
      2,
    ),
  );
  console.log(`\nWrote report: ${reportPath}`);

  if (!apply) {
    console.log("Dry-run only. No rows were written. Re-run with --apply (+ write flag) to update dev.");
    return;
  }

  requireExplicitWriteFlag();
  console.log(`Applying ${updates.length.toLocaleString()} measurement updates to dev public.images…`);
  const batches = [];
  for (let i = 0; i < updates.length; i += 2000) batches.push(updates.slice(i, i + 2000));
  await runPsqlBatches(process.env.DEV_DATABASE_URL, batches);
  console.log(`Done. Updated measurement columns on ${updates.length.toLocaleString()} dev images.`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
