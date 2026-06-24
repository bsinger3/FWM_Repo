#!/usr/bin/env node
/**
 * Apply the 7 manually-entered "blocked" Amazon rows (the ones Amazon soft-blocked,
 * whose title/breadcrumb a human typed into the blocked-manual-entry dashboard).
 *
 *   - 6 live pages -> LLM taxonomy from the entered title+breadcrumb (mapped to the DB's
 *     valid mother categories), written to staging.product_pages.
 *   - B0BQ6L7YP3 -> human marked it 404 (per screenshot; the is_404 flag didn't persist
 *     because the dashboard server predated the is_404 fix). Mark source_status=
 *     'page_not_found' so the search migration (20260623_dev_19) hides its images.
 *
 * Title/breadcrumb come from data-pipelines/products/manual_taxonomy_review/blocked_manual_entries.json
 * (joined by asin). DRY-RUN by default; --apply (+ FWM_DEV_DB_WRITE_OK) executes in one txn.
 */
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
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
const VERSION = "llm_blocked_resolver_v1";

// LLM taxonomy from the entered title+breadcrumb (DB-valid mother categories). __404__ = mark dead.
const DECISIONS = {
  B0D7CPY7HX: { mother: "bottoms", tags: ["trousers"] },          // Dress Pants > Pants>Casual
  B0D6QVTXZH: { mother: "swimwear", tags: ["one-piece-swimsuit"] }, // One Piece Swimsuit > Swimsuits>One-Piece
  B0D631N4VV: { mother: "activewear", tags: ["activewear"] },      // Sweatpants > Active>Active Pants
  B0CSYT9LF3: { mother: "dresses", tags: ["dress"] },              // Club Midi Dress > Dresses
  B0BMTJTMQW: { mother: "dresses", tags: ["dress"] },              // Chiffon Sheath Dress > Dresses
  B0D83WL1LT: { mother: "intimates", tags: [] },                  // Pajama/Lounge pants > Lingerie,Sleep&Lounge
  B0BQ6L7YP3: { mother: "__404__", tags: [] },                    // human-marked dead page
};

function sqlString(v) {
  if (v === null || v === undefined) return "null";
  return `'${String(v).replaceAll("'", "''")}'`;
}
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

  const entries = Object.values(
    JSON.parse(await readFile(path.join(repoRoot, "data-pipelines/products/manual_taxonomy_review/blocked_manual_entries.json"), "utf8")).entries,
  );
  const byAsin = new Map(entries.map((e) => [e.asin, e]));
  const validMothers = new Set(runPsql(databaseUrl, "select id from staging.clothing_mother_categories").trim().split("\n").map((s) => s.trim()));
  const validTags = new Set(runPsql(databaseUrl, "select id from staging.clothing_type_tags").trim().split("\n").map((s) => s.trim()));

  const taxStmts = [];
  const deadAsins = [];
  const plan = [];
  for (const [asin, dec] of Object.entries(DECISIONS)) {
    const e = byAsin.get(asin);
    if (!e) throw new Error(`No saved entry for ${asin}`);
    if (dec.mother === "__404__") {
      deadAsins.push(asin);
      plan.push(`${asin} -> 404 (page_not_found)`);
      continue;
    }
    if (!validMothers.has(dec.mother)) throw new Error(`Invalid mother category ${dec.mother} for ${asin}`);
    const tags = dec.tags.filter((t) => validTags.has(t));
    const breadcrumb = e.breadcrumb || "";
    const evidence = `manual-blocked + LLM: ${(e.title || "").slice(0, 200)}`.slice(0, 480);
    taxStmts.push(`update staging.product_pages set
  mother_category_id = ${sqlString(dec.mother)},
  category_confidence = 'high',
  category_evidence = ${sqlString(evidence)},
  category_source_field = 'llm_blocked_resolver',
  category_extractor_version = ${sqlString(VERSION)},
  category_breadcrumb_path = coalesce(nullif(${sqlString(breadcrumb)}, ''), category_breadcrumb_path),
  category_checked_at = now(),
  needs_manual_review = false
where id = ${uuid(e.product_page_id)};`);
    for (const t of tags) {
      taxStmts.push(`insert into staging.product_page_clothing_type_tags (product_page_id, clothing_type_id, evidence)
values (${uuid(e.product_page_id)}, ${sqlString(t)}, ${sqlString(evidence)})
on conflict (product_page_id, clothing_type_id) do update set evidence = excluded.evidence;`);
    }
    plan.push(`${asin} -> ${dec.mother}${tags.length ? " [" + tags.join(",") + "]" : ""}`);
  }

  const deadIds = deadAsins.map((a) => byAsin.get(a).product_page_id);
  const deadList = deadIds.map(uuid).join(", ");
  const deadStmts = deadIds.length
    ? [
        `update staging.product_pages set source_status='page_not_found', source_http_status=null,
  source_status_checked_at=now(), source_status_evidence='Manually marked dead in blocked-entry dashboard',
  source_status_checker_version='manual_blocked_404_v1' where id in (${deadList});`,
      ]
    : [];

  console.log(`DB:        ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`Plan (7):\n  ${plan.join("\n  ")}`);
  console.log(`Taxonomy updates: ${taxStmts.filter((s) => s.startsWith("update")).length}; tag inserts: ${taxStmts.filter((s) => s.startsWith("insert")).length}; mark-dead: ${deadIds.length}`);

  if (!apply) {
    console.log("\nDry-run only. Re-run with --apply (+ FWM_DEV_DB_WRITE_OK) to execute.");
    return;
  }
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Blocked-resolution apply guard" });
  assertApprovedDevDatabaseUrl(databaseUrl);
  requireExplicitWriteFlag();
  runPsql(databaseUrl, `begin;\n${taxStmts.join("\n")}\n${deadStmts.join("\n")}\ncommit;`);
  console.log(`\nApplied: ${plan.length - deadIds.length} categorized, ${deadIds.length} marked page_not_found.`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
