#!/usr/bin/env node
/**
 * Delete a set of product pages from dev entirely (FK-safe), used to purge
 * non-apparel rows (belts/boots/accessories) the human doesn't want in the catalog.
 *
 * Deletes in order: public.images -> reviews -> staging.product_pages.
 * (images.product_page_id and reviews.product_page_id are ON DELETE NO ACTION;
 *  clothing_type/attribute tags + image_sources cascade; product_card_events.image_id
 *  is SET NULL; image_reports.image_id cascades.) A snapshot of every deleted row is
 *  written BEFORE deleting for reversibility.
 *
 * Input: --from=<json> — a JSON array (or {entries:[...]}) of objects with product_page_id.
 *        Default: FWM_Data/_reports/amazon_backfill_excluded_accessories_shoes.json
 *
 * DRY-RUN by default. --apply (+ FWM_DEV_DB_WRITE_OK) executes. Dev-only.
 */
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { loadDotEnv } from "./lib/local-env.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "./lib/postgres-client.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
await loadDotEnv({ cwd: repoRoot });
const apply = process.argv.includes("--apply");
const fromArg = process.argv.find((a) => a.startsWith("--from="))?.slice(7);
const fromPath = fromArg
  ? path.resolve(fromArg)
  : path.join(fwmDataDir(repoRoot), "_reports", "amazon_backfill_excluded_accessories_shoes.json");

const sqlString = (v) => (v == null ? "null" : `'${String(v).replaceAll("'", "''")}'`);
const uuid = (v) => `${sqlString(v)}::uuid`;
function runPsql(databaseUrl, sql) {
  const c = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(postgresClientTool("psql"), [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "--command", sql], {
      encoding: "utf8",
      env: { ...process.env, ...c.env },
      maxBuffer: 1024 * 1024 * 64,
    });
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

  const raw = JSON.parse(await readFile(fromPath, "utf8"));
  const list = Array.isArray(raw) ? raw : raw.entries || Object.values(raw).find(Array.isArray) || [];
  const ids = [...new Set(list.map((r) => r.product_page_id).filter(Boolean))];
  if (!ids.length) throw new Error(`No product_page_id values in ${fromPath}`);
  const idList = ids.map(uuid).join(", ");

  const counts = runPsql(
    databaseUrl,
    `select
       (select count(*) from staging.product_pages where id in (${idList})),
       (select count(*) from public.images where product_page_id in (${idList})),
       (select count(*) from reviews where product_page_id in (${idList}))`,
  )
    .trim()
    .split("|")
    .map(Number);
  console.log(`Source list:  ${fromPath}`);
  console.log(`DB:           ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`Will delete:  ${counts[0]} product_pages, ${counts[1]} images, ${counts[2]} reviews`);

  if (!apply) {
    console.log("\nDry-run only. Re-run with --apply (+ FWM_DEV_DB_WRITE_OK) to execute.");
    return;
  }
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Delete product pages guard" });
  assertApprovedDevDatabaseUrl(databaseUrl);
  requireExplicitWriteFlag();

  const snap = runPsql(
    databaseUrl,
    `select json_build_object(
       'product_pages', (select coalesce(json_agg(p),'[]') from staging.product_pages p where p.id in (${idList})),
       'images',        (select coalesce(json_agg(i),'[]') from public.images i where i.product_page_id in (${idList})),
       'reviews',       (select coalesce(json_agg(r),'[]') from reviews r where r.product_page_id in (${idList}))
     )`,
  ).trim();
  const snapPath = fromPath.replace(/\.json$/, "_deleted_snapshot.json");
  await writeFile(snapPath, snap + "\n", "utf8");
  console.log(`Snapshot (reversibility) -> ${snapPath}`);

  runPsql(
    databaseUrl,
    `begin;
delete from public.images where product_page_id in (${idList});
delete from reviews where product_page_id in (${idList});
delete from staging.product_pages where id in (${idList});
commit;`,
  );
  console.log(`\nDeleted ${counts[0]} product_pages (+${counts[1]} images, ${counts[2]} reviews).`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
