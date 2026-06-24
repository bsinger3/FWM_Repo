#!/usr/bin/env node
// Clean up out-of-band STRUCTURED measurement garbage in dev public.images that
// the comment parser can't fix (the value never came from the review comment):
//   - Rent-The-Runway weight ranges concatenated into one number ("165-170" ->
//     "165170") => recovered by splitting into plausible chunks (midpoint + a
//     "lo-hi lb" display), or nulled when not cleanly splittable.
//   - implausible weights (>350 or <60 lb) not supported by the comment and
//     impossible heights (>90 in) not supported by the comment => nulled.
//   - comment-supported extremes (real heavy adults, "weigh 355 pounds") are KEPT.
//
// The action plan (with old values for reversibility) is precomputed by the
// Python classifier into:
//   FWM_Data/_reports/measurement_garbage_plan.json
//
// Dev-only + gated. Dry-run unless --apply AND FWM_DEV_DB_WRITE_OK. Touches only
// public.images.

import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  requireExplicitWriteFlag,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs } from "./lib/postgres-client.mjs";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const planPath = path.join(fwmDataDir(repoRoot), "_reports", "measurement_garbage_plan.json");

// Only these three columns are ever touched.
const COLS = [
  ["weight_lbs_display", "numeric", "new_weight_lbs_display"],
  ["weight_display_display", "text", "new_weight_display_display"],
  ["height_in_display", "numeric", "new_height_in_display"],
];

const TAG = "$fwmclamp$";
function updateSql(batch) {
  // Each record sets only the columns present in its plan entry; others keep
  // current value via COALESCE on a sentinel is overkill — instead emit one
  // UPDATE per distinct column-set. Simpler: include all three columns, using
  // the record's new value when the key is present, else the row's own value.
  // We achieve "leave unchanged" by selecting img.<col> when v.<col>_set is false.
  const recordset = COLS.map(([c, t]) => `${c} ${t}, ${c}_set boolean`).join(", ");
  const setClause = COLS.map(([c]) => `${c} = CASE WHEN v.${c}_set THEN v.${c} ELSE img.${c} END`).join(",\n  ");
  const json = JSON.stringify(
    batch.map((rec) => {
      const o = { id: rec.id };
      for (const [c, , key] of COLS) {
        const has = Object.prototype.hasOwnProperty.call(rec, key);
        o[`${c}_set`] = has;
        o[c] = has ? rec[key] : null;
      }
      return o;
    })
  );
  return (
    `UPDATE public.images img SET\n  ${setClause}\n` +
    `FROM jsonb_to_recordset(${TAG}${json}${TAG}::jsonb) AS v(id uuid, ${recordset})\n` +
    `WHERE img.id = v.id;\n`
  );
}

function runPsql(databaseUrl, statements) {
  const connection = postgresConnectionArgs(databaseUrl);
  return new Promise((resolve, reject) => {
    const proc = spawn(postgresClientTool("psql"), [...connection.args, "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"], {
      stdio: ["pipe", "inherit", "inherit"],
      env: { ...process.env, ...connection.env },
    });
    proc.on("error", reject);
    proc.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`psql exited ${code}`))));
    proc.stdin.write("BEGIN;\n");
    for (const s of statements) proc.stdin.write(s);
    proc.stdin.write("COMMIT;\n");
    proc.stdin.end();
  });
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: false });
  printGuardSummary(guard, { prefix: "clamp-measurement-garbage" });

  const plan = JSON.parse(await readFile(planPath, "utf8"));
  const recs = plan.records;
  let recovered = 0, nulledW = 0, nulledH = 0;
  for (const r of recs) {
    if (r.reason?.includes("recover")) recovered++;
    if (r.new_weight_lbs_display === null) nulledW++;
    if (r.new_height_in_display === null) nulledH++;
  }
  console.log(`plan records: ${recs.length}`);
  console.log(`  recover concatenated weight: ${recovered}`);
  console.log(`  null weight: ${nulledW} | null height: ${nulledH}`);
  console.log("\nrecovery samples:");
  recs.filter((r) => r.reason?.includes("recover")).slice(0, 5)
    .forEach((r) => console.log(`  ${r.old_weight_lbs_display} -> ${r.new_weight_lbs_display} (${r.new_weight_display_display})`));

  if (!apply) {
    console.log("\nDry-run. Re-run with --apply (+ write flag) to update dev.");
    return;
  }
  requireExplicitWriteFlag();
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);
  const statements = [];
  for (let i = 0; i < recs.length; i += 1000) statements.push(updateSql(recs.slice(i, i + 1000)));
  console.log(`\nApplying ${recs.length} measurement-garbage fixes to dev public.images…`);
  await runPsql(process.env.DEV_DATABASE_URL, statements);
  console.log("Done.");
}

main().catch((e) => { console.error(e); process.exit(1); });
