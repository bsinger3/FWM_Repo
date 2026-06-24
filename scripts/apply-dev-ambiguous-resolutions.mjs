#!/usr/bin/env node
/**
 * Apply the human-reviewed resolutions for the Amazon backfill's AMBIGUOUS rows:
 *   - APPLY (default 252): trust the LLM's taxonomy proposal — set mother_category_id +
 *     category metadata + breadcrumb path on staging.product_pages, and insert the
 *     clothing-type tags (only those valid in staging.clothing_type_tags; invalid LLM
 *     guesses are skipped + logged).
 *   - REJECT (14): belts/accessories the human marked "rejected" — they don't belong in
 *     the catalog, so DELETE them from dev entirely: images -> reviews -> product_pages
 *     (FK-safe order). product_page_clothing_type_tags / attribute_tags / image_sources
 *     cascade; product_card_events.image_id is SET NULL. A snapshot of every deleted row
 *     is written BEFORE the delete for reversibility.
 *
 * Inputs:
 *   FWM_Data/_reports/residual_taxonomy/ambiguous_decisions_all.ndjson   (266 LLM decisions)
 *   FWM_Data/_reports/residual_taxonomy/ambiguous_rows.ndjson            (breadcrumb source)
 *   data-pipelines/products/manual_taxonomy_review/ambiguous_approvals.json (human: rejected set)
 *
 * DRY-RUN by default. --apply (+ FWM_DEV_DB_WRITE_OK) runs it inside one transaction,
 * after writing the delete snapshot. Dev-only; refuses if DEV==PROD url.
 */
import { execFileSync } from "node:child_process";
import { readFile, writeFile, mkdir } from "node:fs/promises";
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
const VERSION = "llm_ambiguous_resolver_v1";
const residualDir = path.join(fwmDataDir(repoRoot), "_reports", "residual_taxonomy");

function sqlString(v) {
  if (v === null || v === undefined) return "null";
  return `'${String(v).replaceAll("'", "''")}'`;
}
function uuid(v) {
  return `${sqlString(v)}::uuid`;
}
function runPsql(databaseUrl, sql, { write = false } = {}) {
  const c = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...c.env }, maxBuffer: 1024 * 1024 * 128 },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}
async function readNdjson(p) {
  return (await readFile(p, "utf8")).trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

async function main() {
  const databaseUrl = process.env.DEV_DATABASE_URL;
  if (!databaseUrl) throw new Error("DEV_DATABASE_URL is not set (env or .env).");
  if (process.env.PROD_DATABASE_URL && databaseUrl === process.env.PROD_DATABASE_URL) {
    throw new Error("Refusing to run: DEV_DATABASE_URL equals PROD_DATABASE_URL.");
  }

  const decisions = await readNdjson(path.join(residualDir, "ambiguous_decisions_all.ndjson"));
  const rows = await readNdjson(path.join(residualDir, "ambiguous_rows.ndjson"));
  const breadcrumbById = new Map(rows.map((r) => [r.product_page_id, r.breadcrumb || ""]));
  const approvals = JSON.parse(
    await readFile(path.join(repoRoot, "data-pipelines/products/manual_taxonomy_review/ambiguous_approvals.json"), "utf8"),
  );
  const rejectedIds = new Set((approvals.entries || []).filter((e) => e.decision === "rejected").map((e) => e.product_page_id));

  const applyDecisions = decisions.filter((d) => !rejectedIds.has(d.product_page_id));
  const rejectIds = [...rejectedIds];

  // The DB's mother-category FK set (staging.clothing_mother_categories) is COARSER than
  // the clothing-taxonomy.json vocab the LLM used. Map the fine-grained LLM categories to
  // the valid DB ids; the finer detail survives in clothing_type tags + breadcrumb_path.
  const validMothers = new Set(
    runPsql(databaseUrl, "select id from staging.clothing_mother_categories").trim().split("\n").map((s) => s.trim()).filter(Boolean),
  );
  const MOTHER_MAP = { pants: "bottoms", skirts: "bottoms", shorts: "bottoms" };
  const mapMother = (id) => MOTHER_MAP[id] || id;
  const badMothers = [...new Set(applyDecisions.map((d) => mapMother(d.mother_category_id)).filter((m) => !validMothers.has(m)))];
  if (badMothers.length) {
    throw new Error(`Mapped mother_category_id(s) not in staging.clothing_mother_categories: ${badMothers.join(", ")}`);
  }

  // Valid clothing-type tag ids (FK target) — filter out LLM-hallucinated ones.
  const validTags = new Set(
    runPsql(databaseUrl, "select id from staging.clothing_type_tags").trim().split("\n").map((s) => s.trim()).filter(Boolean),
  );
  let skippedTags = 0;
  const skippedTagSet = new Set();

  // ---- TAXONOMY apply SQL (252) ----
  const taxStmts = [];
  for (const d of applyDecisions) {
    const breadcrumb = breadcrumbById.get(d.product_page_id) || "";
    const mother = mapMother(d.mother_category_id);
    const evidence = `LLM(${d.confidence}): ${d.reasoning || ""}`.slice(0, 480);
    taxStmts.push(`update staging.product_pages set
  mother_category_id = ${sqlString(mother)},
  category_confidence = ${sqlString(d.confidence)},
  category_evidence = ${sqlString(evidence)},
  category_source_field = 'llm_ambiguous_resolver',
  category_extractor_version = ${sqlString(VERSION)},
  category_breadcrumb_path = coalesce(nullif(${sqlString(breadcrumb)}, ''), category_breadcrumb_path),
  category_checked_at = now(),
  needs_manual_review = false
where id = ${uuid(d.product_page_id)};`);
    for (const t of d.clothing_type_ids || []) {
      if (!validTags.has(t)) {
        skippedTags += 1;
        skippedTagSet.add(t);
        continue;
      }
      taxStmts.push(`insert into staging.product_page_clothing_type_tags (product_page_id, clothing_type_id, evidence)
values (${uuid(d.product_page_id)}, ${sqlString(t)}, ${sqlString(evidence)})
on conflict (product_page_id, clothing_type_id) do update set evidence = excluded.evidence;`);
    }
  }

  // ---- REJECT delete SQL (14): images -> reviews -> product_pages ----
  const idList = rejectIds.map(uuid).join(", ");
  const delStmts = rejectIds.length
    ? [
        `delete from public.images where product_page_id in (${idList});`,
        `delete from reviews where product_page_id in (${idList});`,
        `delete from staging.product_pages where id in (${idList});`,
      ]
    : [];

  // Report
  const catCounts = {};
  for (const d of applyDecisions) {
    const m = mapMother(d.mother_category_id);
    catCounts[m] = (catCounts[m] || 0) + 1;
  }
  console.log(`DB:                 ${redactDatabaseUrl(databaseUrl)}`);
  console.log(`Apply (taxonomy):   ${applyDecisions.length} pages  -> ${JSON.stringify(catCounts)}`);
  console.log(`Clothing-type tags: ${taxStmts.length - applyDecisions.length} inserts; skipped ${skippedTags} invalid (${[...skippedTagSet].join(", ") || "none"})`);
  console.log(`Reject (delete):    ${rejectIds.length} product_pages (+ their images & reviews)`);

  const planPath = path.join(residualDir, `apply_plan_${apply ? "applied" : "dryrun"}.json`);
  await mkdir(residualDir, { recursive: true });
  await writeFile(
    planPath,
    JSON.stringify(
      { mode: apply ? "apply" : "dry-run", version: VERSION, apply_count: applyDecisions.length, reject_ids: rejectIds, skipped_tags: [...skippedTagSet], category_counts: catCounts },
      null,
      2,
    ) + "\n",
    "utf8",
  );
  console.log(`Wrote plan -> ${planPath}`);

  if (!apply) {
    console.log("\nDry-run only. No rows written. Re-run with --apply (and FWM_DEV_DB_WRITE_OK) to execute.");
    return;
  }

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Ambiguous-resolution apply guard" });
  assertApprovedDevDatabaseUrl(databaseUrl);
  requireExplicitWriteFlag();

  // Snapshot the rows we are about to DELETE (reversibility), before deleting.
  if (rejectIds.length) {
    const snap = runPsql(
      databaseUrl,
      `select json_build_object(
         'product_pages', (select coalesce(json_agg(p), '[]') from staging.product_pages p where p.id in (${idList})),
         'images',        (select coalesce(json_agg(i), '[]') from public.images i where i.product_page_id in (${idList})),
         'reviews',       (select coalesce(json_agg(r), '[]') from reviews r where r.product_page_id in (${idList}))
       )`,
    ).trim();
    const snapPath = path.join(residualDir, "deleted_rejected_snapshot.json");
    await writeFile(snapPath, snap + "\n", "utf8");
    console.log(`Wrote delete snapshot (reversibility) -> ${snapPath}`);
  }

  const txn = `begin;\n${taxStmts.join("\n")}\n${delStmts.join("\n")}\ncommit;`;
  runPsql(databaseUrl, txn, { write: true });
  console.log(`\nApplied: ${applyDecisions.length} taxonomy updates; deleted ${rejectIds.length} belt/accessory pages + their images/reviews.`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
