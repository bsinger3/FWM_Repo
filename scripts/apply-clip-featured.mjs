#!/usr/bin/env node

/*
 * Stage 3 of the CLIP funnel: mark the top-N CLIP-aesthetic images as "featured"
 * in dev public.images so the random page load surfaces them.
 *
 * Reads clip_aesthetic.ndjson ({id, aesthetic}), takes the top N by score, and sets
 *     featured_rank = 1..N   (1 = best)
 * on those rows (clearing any prior featured_rank first). Reversible: undo by
 * setting featured_rank = null. Column created if missing.
 *
 * Dry-run by default; --apply + FWM_DEV_DB_WRITE_OK writes. Dev-only, gated.
 *
 *   node scripts/apply-clip-featured.mjs --top 100
 *   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev node scripts/apply-clip-featured.mjs --apply --top 100
 */
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
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
const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : d;
};
const TOP = Math.max(1, Number(arg("top", "100")) || 100);
const inputPath = arg("input", path.join(fwmDataDir(repoRoot), "_cache", "clip_aesthetic.ndjson"));

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

  const raw = await readFile(inputPath, "utf8");
  const rows = raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l))
    .filter((r) => r.id && Number.isFinite(r.aesthetic));
  rows.sort((a, b) => b.aesthetic - a.aesthetic);
  const top = rows.slice(0, TOP);

  console.log(`DB:     ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`Scored: ${rows.length} | featuring top ${top.length}`);
  console.log(`Aesthetic range featured: ${top[0].aesthetic} (#1) .. ${top[top.length - 1].aesthetic} (#${top.length})`);
  console.log(`Sample top 5: ${top.slice(0, 5).map((r) => `${r.id.slice(0, 8)}=${r.aesthetic}`).join(", ")}`);

  if (!apply) {
    console.log("\nDry-run only. Re-run with --apply (+ FWM_DEV_DB_WRITE_OK) to set featured_rank.");
    return;
  }

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "CLIP featured guard" });
  requireExplicitWriteFlag();

  runPsql(databaseUrl, `alter table public.images add column if not exists featured_rank int;`);
  const cases = top.map((r, i) => `when id = ${uuid(r.id)} then ${i + 1}`).join("\n        ");
  runPsql(
    databaseUrl,
    `begin;
     update public.images set featured_rank = null where featured_rank is not null;
     update public.images
        set featured_rank = case
        ${cases}
        else null end
      where id in (${top.map((r) => uuid(r.id)).join(", ")});
     commit;`,
  );
  const n = Number(runPsql(databaseUrl, `select count(*) from public.images where featured_rank is not null`).trim());
  console.log(`\nDone. featured_rank set on ${n} rows (1=best). Undo: set featured_rank = null.`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
