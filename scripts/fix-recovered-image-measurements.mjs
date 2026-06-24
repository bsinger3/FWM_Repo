#!/usr/bin/env node
// One-off cleanup: after restoring user_comment for the file-path-corrupted rows,
// re-set their measurement columns to the MERGE of (new-parser extraction of the
// recovered comment) over (the authoritative intake CSV *_display values).
//
// Why merge, not comment-only: many retailers (e.g. Quince) capture height/weight
// as STRUCTURED reviewer attributes (height_raw="I am 5ft4in") that are NOT in the
// free-text comment. A comment-only re-extraction wrongly clears those. The merged
// values are computed by the sibling python step into /tmp/measurement_fix.json:
//   { <image_id>: { height_in_display, weight_lbs_display, waist_in, hips_in_display,
//                   bust_in_display, bra_band_in_display, cupsize_display,
//                   inseam_inches_display, age_years_display } }
//
// Dev-only + gated. Dry-run unless --apply AND FWM_DEV_DB_WRITE_OK. Touches only
// public.images.

import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  requireExplicitWriteFlag,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs } from "./lib/postgres-client.mjs";

const apply = process.argv.includes("--apply");
const FIX_PATH = "/tmp/measurement_fix.json";

const NUMERIC = new Set([
  "height_in_display", "weight_lbs_display", "waist_in", "hips_in_display",
  "bust_in_display", "bra_band_in_display", "inseam_inches_display",
]);
const COLS = [
  ["height_in_display", "numeric"], ["weight_lbs_display", "numeric"], ["waist_in", "numeric"],
  ["hips_in_display", "numeric"], ["bust_in_display", "numeric"], ["bra_band_in_display", "numeric"],
  ["cupsize_display", "text"], ["inseam_inches_display", "numeric"], ["age_years_display", "integer"],
];

function cell(col, v) {
  const s = String(v ?? "").trim();
  if (!s) return null;
  if (col === "cupsize_display") return s;
  const n = Number(s);
  if (!Number.isFinite(n)) return null;
  return col === "age_years_display" ? Math.round(n) : n;
}

const TAG = "$fwmfix$";
function updateSql(batch) {
  const recordset = COLS.map(([c, t]) => `${c} ${t}`).join(", ");
  const setClause = COLS.map(([c]) => `${c} = v.${c}`).join(",\n  ");
  const json = JSON.stringify(
    batch.map(([id, fields]) => {
      const o = { id };
      for (const [c] of COLS) o[c] = cell(c, fields[c]);
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
  const guard = await assertApprovedDevSupabase({ cwd: process.cwd(), requireServiceRoleKey: false });
  printGuardSummary(guard, { prefix: "fix-recovered-measurements" });

  const fix = JSON.parse(await readFile(FIX_PATH, "utf8"));
  const entries = Object.entries(fix);
  let withHeight = 0, withWeight = 0;
  for (const [, f] of entries) {
    if (cell("height_in_display", f.height_in_display) != null) withHeight++;
    if (cell("weight_lbs_display", f.weight_lbs_display) != null) withWeight++;
  }
  console.log(`rows to update: ${entries.length}`);
  console.log(`  with height: ${withHeight} | with weight: ${withWeight}`);

  if (!apply) {
    console.log("\nDry-run. Re-run with --apply (+ write flag) to update dev.");
    return;
  }
  requireExplicitWriteFlag();
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);
  const statements = [];
  for (let i = 0; i < entries.length; i += 1000) statements.push(updateSql(entries.slice(i, i + 1000)));
  console.log(`\nApplying ${entries.length} measurement merges to dev public.images…`);
  await runPsql(process.env.DEV_DATABASE_URL, statements);
  console.log("Done.");
}

main().catch((e) => { console.error(e); process.exit(1); });
