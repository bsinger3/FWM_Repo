#!/usr/bin/env node
/**
 * Promote the main Amazon free-HTTP backfill classifications into dev
 * staging.product_pages. Reads the completed progress sidecar (dedup by
 * product_page_id, last line wins) and writes, for every row that got a confident
 * primaryCategory: mother_category_id + category metadata + breadcrumb_path +
 * clothing-type tags (filtered to valid staging.clothing_type_tags ids).
 *
 * EXCLUDES mother categories 'accessories' and 'shoes' (belts/boots) by default —
 * the human has said those don't belong in the catalog; they're written to an
 * excluded list for a separate decision (keep --include-accessories-shoes to override).
 *
 * All backfill mother categories are already DB-valid (the deterministic classifier
 * emits the coarse set), so no category remap is needed here.
 *
 * DRY-RUN by default. --apply (+ FWM_DEV_DB_WRITE_OK) runs the generated SQL via
 * `psql -f` in a single transaction. Dev-only.
 */
import { execFileSync } from "node:child_process";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
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
const includeAccShoes = process.argv.includes("--include-accessories-shoes");
const VERSION = "amazon_free_http_backfill_v7";
const EXCLUDE = new Set(includeAccShoes ? [] : ["accessories", "shoes"]);

function sqlString(v) {
  if (v === null || v === undefined) return "null";
  return `'${String(v).replaceAll("'", "''")}'`;
}
const uuid = (v) => `${sqlString(v)}::uuid`;
function psql(databaseUrl, extraArgs) {
  const c = postgresConnectionArgs(databaseUrl);
  return execFileSync(postgresClientTool("psql"), [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", ...extraArgs], {
    encoding: "utf8",
    env: { ...process.env, ...c.env },
    maxBuffer: 1024 * 1024 * 128,
  });
}

async function main() {
  const databaseUrl = process.env.DEV_DATABASE_URL;
  if (!databaseUrl) throw new Error("DEV_DATABASE_URL is not set.");
  if (process.env.PROD_DATABASE_URL && databaseUrl === process.env.PROD_DATABASE_URL) {
    throw new Error("Refusing to run: DEV_DATABASE_URL equals PROD_DATABASE_URL.");
  }

  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  const sidecar = path.join(reportsDir, "amazon_taxonomy_worklist_20260619T182108730Z_progress.ndjson");
  const byId = new Map();
  for (const line of (await readFile(sidecar, "utf8")).trim().split("\n")) {
    try {
      const r = JSON.parse(line);
      if (r.product_page_id) byId.set(r.product_page_id, r);
    } catch {}
  }

  const validTags = new Set(psql(databaseUrl, ["--command", "select id from staging.clothing_type_tags"]).trim().split("\n").map((s) => s.trim()));
  const validMothers = new Set(psql(databaseUrl, ["--command", "select id from staging.clothing_mother_categories"]).trim().split("\n").map((s) => s.trim()));

  const stmts = [];
  const counts = {};
  const excluded = [];
  let pages = 0;
  let tagInserts = 0;
  const badMothers = new Set();

  for (const r of byId.values()) {
    const pc = r.proposed?.primaryCategory;
    if (r.skipped || !pc?.mother_category_id) continue;
    const m = pc.mother_category_id;
    if (EXCLUDE.has(m)) {
      excluded.push({ product_page_id: r.product_page_id, asin: r.asin, mother_category_id: m, title: r.extracted_fields_preview?.title || "" });
      continue;
    }
    if (!validMothers.has(m)) {
      badMothers.add(m);
      continue;
    }
    pages += 1;
    counts[m] = (counts[m] || 0) + 1;
    const breadcrumb = r.extracted_fields_preview?.breadcrumb || "";
    const evidence = String(pc.category_evidence || "").slice(0, 480);
    stmts.push(`update staging.product_pages set
  mother_category_id = ${sqlString(m)},
  category_confidence = ${sqlString(pc.category_confidence)},
  category_evidence = ${sqlString(evidence)},
  category_source_field = ${sqlString(pc.category_source_field)},
  category_extractor_version = ${sqlString(VERSION)},
  category_breadcrumb_path = coalesce(nullif(${sqlString(breadcrumb)}, ''), category_breadcrumb_path),
  category_checked_at = now(),
  needs_manual_review = false
where id = ${uuid(r.product_page_id)};`);
    for (const tag of r.proposed.itemTags || []) {
      const t = tag.clothing_type_id;
      if (!validTags.has(t)) continue;
      tagInserts += 1;
      stmts.push(`insert into staging.product_page_clothing_type_tags (product_page_id, clothing_type_id, evidence)
values (${uuid(r.product_page_id)}, ${sqlString(t)}, ${sqlString(String(tag.evidence || "").slice(0, 480))})
on conflict (product_page_id, clothing_type_id) do update set evidence = excluded.evidence;`);
    }
  }

  if (badMothers.size) throw new Error(`Unexpected invalid mother categories: ${[...badMothers].join(", ")}`);

  await mkdir(reportsDir, { recursive: true });
  const exclPath = path.join(reportsDir, "amazon_backfill_excluded_accessories_shoes.json");
  await writeFile(exclPath, JSON.stringify(excluded, null, 2) + "\n", "utf8");

  console.log(`DB:                ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`Pages to promote:  ${pages}`);
  console.log(`  by category:     ${JSON.stringify(counts)}`);
  console.log(`Clothing-type tag inserts: ${tagInserts}`);
  console.log(`EXCLUDED (accessories/shoes): ${excluded.length} -> ${exclPath}`);

  if (!apply) {
    console.log("\nDry-run only. No rows written. Re-run with --apply (+ FWM_DEV_DB_WRITE_OK) to execute.");
    return;
  }

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Amazon backfill promote guard" });
  assertApprovedDevDatabaseUrl(databaseUrl);
  requireExplicitWriteFlag();

  // 4k+ statements exceed ARG_MAX for --command; write to a temp file and use psql -f.
  const sqlFile = path.join(os.tmpdir(), `promote_amazon_backfill_${pages}.sql`);
  await writeFile(sqlFile, `begin;\n${stmts.join("\n")}\ncommit;\n`, "utf8");
  psql(databaseUrl, ["--file", sqlFile]);
  console.log(`\nApplied: promoted ${pages} pages (${tagInserts} tags). Excluded ${excluded.length} accessories/shoes (see ${exclPath}).`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
