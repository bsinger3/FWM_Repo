#!/usr/bin/env node
/**
 * Apply flagged-image review decisions to dev public.images (SOFT-HIDE, dev-only).
 *
 * Reads the decisions file written by the flagged-image-review dashboard
 * (tools/flagged-image-review/data/decisions.json) and, for every image marked
 * "remove", soft-hides it by setting:
 *     removed_at     = now()
 *     removed_reason = 'flagged: <reasons>'
 * Images marked "keep" that were previously removed get removed_at cleared (undo).
 * The row is never deleted — the dev frontend filters on `removed_at is null`.
 *
 * The `removed_at` / `removed_reason` columns are created if missing
 * (ALTER TABLE ... ADD COLUMN IF NOT EXISTS), so this is the column's home.
 *
 * DRY-RUN by default. --apply (+ FWM_DEV_DB_WRITE_OK + service-role key) executes.
 * A snapshot of every affected row is written BEFORE the update for reversibility.
 * Dev-only: refuses any URL that doesn't carry the approved dev project ref.
 */
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadDotEnv } from "./lib/local-env.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "./lib/postgres-client.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
await loadDotEnv({ cwd: repoRoot });

const apply = process.argv.includes("--apply");
const decisionsPath = path.join(repoRoot, "tools/flagged-image-review/data/decisions.json");
const datasetPath = path.join(repoRoot, "tools/flagged-image-review/data/flagged-dataset.json");

const sqlString = (v) => (v == null ? "null" : `'${String(v).replaceAll("'", "''")}'`);
const uuid = (v) => `${sqlString(v)}::uuid`;

function runPsql(databaseUrl, sql) {
  const c = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...c.env }, maxBuffer: 1024 * 1024 * 64 },
    );
  } catch (e) {
    throw new Error(String(e.stderr || e.message || "").replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

async function main() {
  const databaseUrl = process.env.DEV_DATABASE_URL;
  if (!databaseUrl) throw new Error("DEV_DATABASE_URL is not set.");
  if (process.env.PROD_DATABASE_URL && databaseUrl === process.env.PROD_DATABASE_URL) {
    throw new Error("Refusing to run: DEV_DATABASE_URL equals PROD_DATABASE_URL.");
  }
  assertApprovedDevDatabaseUrl(databaseUrl);

  if (!existsSync(decisionsPath)) {
    throw new Error(`No decisions file at ${decisionsPath}. Make decisions in the dashboard first (npm run flagged-review).`);
  }
  const decisions = JSON.parse(await readFile(decisionsPath, "utf8"));

  // Reason context per image, for a human-readable removed_reason.
  let reasonsById = {};
  if (existsSync(datasetPath)) {
    const ds = JSON.parse(await readFile(datasetPath, "utf8"));
    for (const e of ds.entries) reasonsById[e.image_id] = e.reasons;
  }

  const toRemove = [];
  const toKeep = [];
  for (const [id, d] of Object.entries(decisions)) {
    if (d.decision === "remove") toRemove.push(id);
    else if (d.decision === "keep") toKeep.push(id);
  }

  console.log(`DB:            ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`Decisions:     ${path.relative(repoRoot, decisionsPath)}`);
  console.log(`Mark removed:  ${toRemove.length}`);
  console.log(`Clear removed: ${toKeep.length} (keep decisions, undo any prior soft-hide)`);

  if (!toRemove.length && !toKeep.length) {
    console.log("\nNothing to do — no remove/keep decisions recorded.");
    return;
  }

  // Verify the target ids actually exist in dev.
  const allIds = [...new Set([...toRemove, ...toKeep])];
  const present = Number(
    runPsql(databaseUrl, `select count(*) from public.images where id in (${allIds.map(uuid).join(", ")})`).trim(),
  );
  console.log(`Present in dev images: ${present} / ${allIds.length}`);

  if (!apply) {
    console.log("\nDry-run only. Re-run with --apply (+ FWM_DEV_DB_WRITE_OK) to execute.");
    if (toRemove.length) console.log(`Would soft-hide: ${toRemove.slice(0, 5).join(", ")}${toRemove.length > 5 ? " …" : ""}`);
    return;
  }

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Flagged removals guard" });
  requireExplicitWriteFlag();

  // Ensure the soft-hide columns exist (idempotent).
  runPsql(
    databaseUrl,
    `alter table public.images
       add column if not exists removed_at timestamptz,
       add column if not exists removed_reason text;`,
  );

  // Snapshot affected rows BEFORE mutating, for reversibility.
  const snap = runPsql(
    databaseUrl,
    `select coalesce(json_agg(json_build_object(
        'id', id, 'removed_at', removed_at, 'removed_reason', removed_reason,
        'original_url_display', original_url_display, 'user_comment', user_comment
      )), '[]')
     from public.images where id in (${allIds.map(uuid).join(", ")});`,
  ).trim();
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const snapPath = path.join(repoRoot, "tools/flagged-image-review/data", `applied_snapshot_${stamp}.json`);
  await writeFile(snapPath, snap + "\n", "utf8");
  console.log(`Snapshot (reversibility) -> ${path.relative(repoRoot, snapPath)}`);

  // Build per-image removed_reason from the flag reasons.
  const removeCases = toRemove
    .map((id) => {
      const reasons = (reasonsById[id] || ["flagged"]).join(", ");
      return `when id = ${uuid(id)} then ${sqlString("flagged: " + reasons)}`;
    })
    .join("\n        ");

  const stmts = ["begin;"];
  if (toRemove.length) {
    stmts.push(
      `update public.images
         set removed_at = now(),
             removed_reason = case
        ${removeCases}
        else 'flagged' end
       where id in (${toRemove.map(uuid).join(", ")});`,
    );
  }
  if (toKeep.length) {
    stmts.push(
      `update public.images
         set removed_at = null, removed_reason = null
       where id in (${toKeep.map(uuid).join(", ")}) and removed_at is not null;`,
    );
  }
  stmts.push("commit;");
  runPsql(databaseUrl, stmts.join("\n"));

  const nowRemoved = Number(
    runPsql(databaseUrl, `select count(*) from public.images where removed_at is not null`).trim(),
  );
  console.log(`\nDone. Soft-hid ${toRemove.length}, restored ${toKeep.length}.`);
  console.log(`Total rows now flagged removed in dev: ${nowRemoved}`);
  console.log(`The dev frontend should filter "removed_at is null". To undo, restore from the snapshot above.`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
