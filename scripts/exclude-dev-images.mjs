#!/usr/bin/env node

/*
 * Targeted reversible soft-hide of specific images in dev public.images (dev-only).
 *
 * Sets the same columns the flagged-image-review path uses:
 *     removed_at     = now()
 *     removed_reason = '<reason>'
 * The dev frontend filters on `removed_at is null`. The row is NEVER deleted; undo
 * by clearing removed_at (a snapshot of every affected row is written first).
 *
 * Use for one-off exclusions (e.g. wrong-subject images) without touching the
 * shared flagged-review decisions.json.
 *
 *   node scripts/exclude-dev-images.mjs --reason "wrong subject (male)" <id> <id> ...
 *   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
 *     node scripts/exclude-dev-images.mjs --apply --reason "..." <id> ...
 */
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
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
function argValue(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const reason = argValue("reason", "excluded");
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ids = process.argv.slice(2).filter((a) => UUID_RE.test(a));

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
  if (!ids.length) throw new Error("No image ids passed. Usage: --reason \"…\" <uuid> <uuid> ...");
  const databaseUrl = process.env.DEV_DATABASE_URL;
  if (!databaseUrl) throw new Error("DEV_DATABASE_URL is not set.");
  if (process.env.PROD_DATABASE_URL && databaseUrl === process.env.PROD_DATABASE_URL) {
    throw new Error("Refusing to run: DEV_DATABASE_URL equals PROD_DATABASE_URL.");
  }
  assertApprovedDevDatabaseUrl(databaseUrl);

  console.log(`DB:      ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`Reason:  ${reason}`);
  console.log(`Ids:     ${ids.length}`);
  // Show the target rows (read-only) so the change is reviewable before --apply.
  const preview = runPsql(
    databaseUrl,
    `select id, left(coalesce(original_url_display,''), 70), coalesce(user_comment,'')
       from public.images where id in (${ids.map(uuid).join(", ")});`,
  ).trim();
  console.log("Target rows in dev:\n" + (preview || "  (none found!)"));

  if (!apply) {
    console.log("\nDry-run only. Re-run with --apply (+ FWM_DEV_DB_WRITE_OK) to soft-hide these.");
    return;
  }

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Exclude-images guard" });
  requireExplicitWriteFlag();

  runPsql(
    databaseUrl,
    `alter table public.images
       add column if not exists removed_at timestamptz,
       add column if not exists removed_reason text;`,
  );

  const snap = runPsql(
    databaseUrl,
    `select coalesce(json_agg(json_build_object(
        'id', id, 'removed_at', removed_at, 'removed_reason', removed_reason,
        'original_url_display', original_url_display, 'user_comment', user_comment
      )), '[]')
     from public.images where id in (${ids.map(uuid).join(", ")});`,
  ).trim();
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const snapPath = path.join(repoRoot, "..", "FWM_Data", "_reports", `exclude_images_snapshot_${stamp}.json`);
  await writeFile(snapPath, snap + "\n", "utf8");
  console.log(`Snapshot (reversibility) -> ${snapPath}`);

  runPsql(
    databaseUrl,
    `begin;
     update public.images
        set removed_at = now(), removed_reason = ${sqlString("flagged: " + reason)}
      where id in (${ids.map(uuid).join(", ")});
     commit;`,
  );
  const nowRemoved = Number(
    runPsql(databaseUrl, `select count(*) from public.images where removed_at is not null`).trim(),
  );
  console.log(`\nDone. Soft-hid ${ids.length}. Total flagged-removed in dev: ${nowRemoved}.`);
  console.log("Undo: restore removed_at/removed_reason from the snapshot above (or set removed_at = null).");
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
