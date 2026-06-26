#!/usr/bin/env node
/**
 * Apply the human-approved re-categorizations from the "other"-category approval
 * dashboard to DEV.
 *
 * Reads tools/other-category-approval/data/decisions.json (written by the
 * dashboard). Two kinds of decision:
 *   - recategorize: set staging.product_pages.mother_category_id to the chosen
 *     category (only where it is still 'other') + propagate to public.images.
 *   - remove: the row is not clothing / doesn't belong — DELETE it from
 *     staging.product_pages and delete its images (FK-safe: images -> reviews ->
 *     product_pages), so it leaves both the catalog and search.
 * Any brand-new category typed in the dashboard is first inserted into BOTH
 * staging.clothing_mother_categories (the FK target) and
 * public.clothing_mother_categories (the frontend dropdown mirror). After writes
 * it refreshes the search matview.
 *
 * Dev-only + dry-run by default. Writes require --apply AND
 * FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev. A full before-snapshot of every
 * touched row is written to FWM_Data/_reports for reversibility.
 *
 *   node scripts/apply-dev-other-category-approvals.mjs            # dry run
 *   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
 *     node scripts/apply-dev-other-category-approvals.mjs --apply  # write
 */

import { execFileSync } from "node:child_process";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";

const apply = process.argv.includes("--apply");
const toolDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "tools", "other-category-approval");
const decisionsPath = path.join(toolDir, "data", "decisions.json");
const EXTRACTOR_VERSION = "other_category_dashboard_v1";
const SOURCE_FIELD = "manual_other_category_approval";

function runPsql(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...connection.env }, maxBuffer: 1024 * 1024 * 100 },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlTextArray(values) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  if (!items.length) return "array[]::text[]";
  return `array[${items.map(sqlString).join(",")}]::text[]`;
}

function titleCase(slug) {
  return String(slug || "")
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

async function main() {
  const guard = await assertApprovedDevSupabase();
  printGuardSummary(guard, { prefix: "apply-other-category-approvals" });
  const databaseUrl = process.env.DEV_DATABASE_URL;
  assertApprovedDevDatabaseUrl(databaseUrl);

  if (!existsSync(decisionsPath)) {
    throw new Error(`No decisions file at ${decisionsPath}. Approve rows in the dashboard first.`);
  }
  const decisions = Object.values(JSON.parse(await readFile(decisionsPath, "utf8")));
  if (!decisions.length) {
    console.log("No decisions to apply.");
    return;
  }

  const removeDecisions = decisions.filter((d) => d.decision === "remove");
  const recatDecisions = decisions.filter((d) => d.decision !== "remove");

  const existingCats = new Set(
    runPsql(databaseUrl, "select id from staging.clothing_mother_categories;").trim().split("\n").map((s) => s.trim()).filter(Boolean),
  );

  // Validate recategorizations and collect any brand-new categories.
  const valid = [];
  const newCats = new Map();
  const skipped = [];
  for (const d of recatDecisions) {
    const chosen = d.chosen_mother_category_id;
    if (!chosen || chosen === "other") { skipped.push({ id: d.product_page_id, why: "no real category" }); continue; }
    if (!existingCats.has(chosen) && !newCats.has(chosen)) newCats.set(chosen, titleCase(chosen));
    valid.push({
      id: d.product_page_id,
      chosen,
      is_new: !existingCats.has(chosen),
      clothing_type_id: d.clothing_type_id || null,
      new_product_title: typeof d.new_product_title === "string" && d.new_product_title.trim() ? d.new_product_title.trim() : null,
    });
  }

  const removeIds = [...new Set(removeDecisions.map((d) => d.product_page_id).filter(Boolean))];

  // Confirm the rows are still 'other' (don't clobber rows another pass already fixed).
  const ids = valid.map((v) => sqlString(v.id)).join(",");
  const liveOther = new Set(
    ids
      ? runPsql(databaseUrl, `select id::text from staging.product_pages where id in (${ids}) and mother_category_id = 'other';`)
          .trim().split("\n").map((s) => s.trim()).filter(Boolean)
      : [],
  );
  const willUpdate = valid.filter((v) => liveOther.has(v.id));
  const alreadyMoved = valid.filter((v) => !liveOther.has(v.id));

  const byCat = {};
  for (const v of willUpdate) byCat[v.chosen] = (byCat[v.chosen] || 0) + 1;

  // Count what the removals will delete (FK-safe: images + reviews + the page).
  let removeCounts = [0, 0, 0];
  if (removeIds.length) {
    const ridList = removeIds.map((id) => sqlString(id) + "::uuid").join(",");
    removeCounts = runPsql(
      databaseUrl,
      `select
         (select count(*) from staging.product_pages where id in (${ridList})),
         (select count(*) from public.images where product_page_id in (${ridList})),
         (select count(*) from reviews where product_page_id in (${ridList}))`,
    ).trim().split("|").map(Number);
  }

  console.log(`\nDecisions: ${decisions.length} (${recatDecisions.length} recategorize, ${removeDecisions.length} remove)`);
  const titleOverrides = willUpdate.filter((v) => v.new_product_title).length;
  console.log(`Will recategorize (still 'other'): ${willUpdate.length}` + (titleOverrides ? ` (incl. ${titleOverrides} title fixes)` : ""));
  console.log(`Skipped (no real category): ${skipped.length}`);
  console.log(`Already non-'other' (left as-is): ${alreadyMoved.length}`);
  console.log(`Will DELETE: ${removeCounts[0]} product_pages, ${removeCounts[1]} images, ${removeCounts[2]} reviews`);
  if (newCats.size) {
    console.log(`\nNEW categories to create (staging + public mirror):`);
    for (const [id, label] of newCats) console.log(`  ${id}  (label: ${label})`);
  }
  console.log(`\nTarget category distribution:`);
  for (const [k, v] of Object.entries(byCat).sort((a, b) => b[1] - a[1])) console.log(`  ${k.padEnd(14)} ${v}`);

  if (!willUpdate.length && !removeIds.length) {
    console.log(`\nNothing to update or remove.`);
    return;
  }

  if (!apply) {
    console.log(`\nDRY RUN — no DB writes. Re-run with --apply (and FWM_DEV_DB_WRITE_OK) to apply.`);
    return;
  }

  requireExplicitWriteFlag();

  const updateIds = willUpdate.map((v) => sqlString(v.id) + "::uuid").join(",");
  const ridList = removeIds.map((id) => sqlString(id) + "::uuid").join(",");

  // Reversible snapshot: the before-state of recategorized rows AND the full
  // rows (pages + images + reviews) we are about to delete.
  const recatBefore = updateIds
    ? JSON.parse(
        runPsql(
          databaseUrl,
          `select coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb) from (
             select id::text, mother_category_id, product_title_raw, category_confidence,
                    category_evidence, category_source_field, category_extractor_version,
                    observed_clothing_type_ids, category_checked_at
             from staging.product_pages where id in (${updateIds})
           ) t;`,
        ).trim() || "[]",
      )
    : [];
  const deletedSnapshot = ridList
    ? JSON.parse(
        runPsql(
          databaseUrl,
          `select json_build_object(
             'product_pages', (select coalesce(json_agg(p),'[]') from staging.product_pages p where p.id in (${ridList})),
             'images',        (select coalesce(json_agg(i),'[]') from public.images i where i.product_page_id in (${ridList})),
             'reviews',       (select coalesce(json_agg(r),'[]') from reviews r where r.product_page_id in (${ridList}))
           )`,
        ).trim() || "{}",
      )
    : {};
  const reportDir = path.join(fwmDataDir(), "_reports");
  await mkdir(reportDir, { recursive: true });
  const stem = new Date().toISOString().replace(/[-:]/g, "").replace(".", "").slice(0, 15);
  const snapshotPath = path.join(reportDir, `other_category_approvals_${stem}_before.json`);
  await writeFile(
    snapshotPath,
    JSON.stringify(
      { snapshot_at: new Date().toISOString(), new_categories: [...newCats], recategorized: recatBefore, deleted: deletedSnapshot },
      null,
      2,
    ),
  );
  console.log(`\nReversible snapshot: ${snapshotPath}`);

  // One transaction: new categories, recat updates, propagate, then FK-safe deletes.
  const stmts = [];
  let nextSort = Number(runPsql(databaseUrl, "select coalesce(max(sort_order),0) from staging.clothing_mother_categories;").trim()) || 100;
  for (const [id, label] of newCats) {
    nextSort += 5;
    stmts.push(
      `insert into staging.clothing_mother_categories (id, label, display_label, sort_order, frontend_sort_order, is_frontend_filter, created_at, updated_at)
         values (${sqlString(id)}, ${sqlString(label)}, ${sqlString(label)}, ${nextSort}, ${nextSort}, true, now(), now())
         on conflict (id) do nothing;`,
    );
    stmts.push(
      `insert into public.clothing_mother_categories (id, label, sort_order)
         values (${sqlString(id)}, ${sqlString(label)}, ${nextSort})
         on conflict (id) do nothing;`,
    );
  }
  for (const v of willUpdate) {
    const setTypes = v.clothing_type_id
      ? `observed_clothing_type_ids = ${sqlTextArray([v.clothing_type_id])},`
      : "";
    const setTitle = v.new_product_title ? `product_title_raw = ${sqlString(v.new_product_title)},` : "";
    stmts.push(
      `update staging.product_pages set
         mother_category_id = ${sqlString(v.chosen)},
         category_confidence = 'high',
         category_evidence = ${sqlString(`human-approved via other-category dashboard (was 'other')`)},
         category_source_field = ${sqlString(SOURCE_FIELD)},
         category_extractor_version = ${sqlString(EXTRACTOR_VERSION)},
         ${setTypes}${setTitle}
         category_checked_at = now(), updated_at = now()
       where id = ${sqlString(v.id)} and mother_category_id = 'other';`,
    );
  }
  if (updateIds) {
    stmts.push(
      `update public.images i set mother_category_id = p.mother_category_id
         from staging.product_pages p
         where i.product_page_id = p.id and p.id in (${updateIds});`,
    );
  }
  if (ridList) {
    // FK-safe delete order: images -> reviews -> product_pages.
    stmts.push(`delete from public.images where product_page_id in (${ridList});`);
    stmts.push(`delete from reviews where product_page_id in (${ridList});`);
    stmts.push(`delete from staging.product_pages where id in (${ridList});`);
  }
  runPsql(databaseUrl, `begin;\n${stmts.join("\n")}\ncommit;`);
  console.log(
    `\nAPPLIED: re-categorized ${willUpdate.length} product pages` +
      (ridList ? `; DELETED ${removeCounts[0]} pages (+${removeCounts[1]} images, ${removeCounts[2]} reviews)` : "") +
      ` (+ propagated to public.images).`,
  );

  // Search reads the matview; refresh so the re-categorized rows show their new
  // category. CONCURRENTLY can't run inside a transaction.
  try {
    runPsql(databaseUrl, "refresh materialized view concurrently public.searchable_images;");
    console.log(`Refreshed public.searchable_images.`);
  } catch (error) {
    console.log(`WARNING: matview refresh failed (${error.message}). Run manually:`);
    console.log(`  refresh materialized view concurrently public.searchable_images;`);
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
