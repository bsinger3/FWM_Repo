#!/usr/bin/env node
// One-off dev cleanup of rows that can never surface / are broken, from the
// 2026-06-25 data audit:
//   - the 1 fully-orphan image (product_page_id IS NULL  ==  the null review_id row)
//   - the 113 images that never got source dimensions (persistent dead-URL fetches;
//     107 are still fail-open in search as broken thumbnails)
//   - every staging.product_pages row that ends up with ZERO images afterward
//     (the 9 already image-less + the 8 whose only images were the dead ones above),
//     plus those pages' reviews.
//
// FK-safe order: delete images (image_reports/image_vectors CASCADE,
// product_card_events SET NULL) -> delete reviews on now-zero-image pages ->
// delete those pages (clothing_type_tags/attribute_tags/image_sources CASCADE).
//
// Dry-run by default. --apply requires FWM_DEV_DB_WRITE_OK. Full before-state is
// snapshotted to FWM_Data/_reports for reversibility.
//
//   node scripts/cleanup-dev-orphan-rows.mjs            # dry run
//   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
//     node scripts/cleanup-dev-orphan-rows.mjs --apply

import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "./lib/postgres-client.mjs";

const apply = process.argv.includes("--apply");

// Images to delete: fully-orphan (no product_page_id) OR no source dimensions.
const IMG_PRED = "(product_page_id is null or review_id is null or source_width_px is null or source_height_px is null)";
// Pages to delete: zero images remaining once the above images are gone.
const ZERO_PAGES = `select p.id from staging.product_pages p
  where not exists (select 1 from public.images i where i.product_page_id = p.id and not (${IMG_PRED}))`;

function runPsql(databaseUrl, sql) {
  const c = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...c.env }, maxBuffer: 1024 * 1024 * 200 },
    );
  } catch (e) {
    throw new Error(String(e.stderr || e.message || "").replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

async function main() {
  const guard = await assertApprovedDevSupabase({ requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "cleanup-orphan-rows" });
  const databaseUrl = process.env.DEV_DATABASE_URL;
  assertApprovedDevDatabaseUrl(databaseUrl);

  const n = (sql) => Number(runPsql(databaseUrl, sql).trim() || "0");
  const imgCount = n(`select count(*) from public.images where ${IMG_PRED};`);
  const pageCount = n(`select count(*) from (${ZERO_PAGES}) z;`);
  const reviewCount = n(`select count(*) from public.reviews where product_page_id in (${ZERO_PAGES});`);
  // Safety: any SURVIVING image whose review_id points at a review we'd delete?
  const danglingReviewRefs = n(
    `select count(*) from public.images i
       where ${IMG_PRED} = false
         and i.review_id in (select id from public.reviews where product_page_id in (${ZERO_PAGES}));`,
  );

  console.log(`\nWill DELETE:`);
  console.log(`  images:        ${imgCount}  (1 orphan + 113 no-dimension dead fetches)`);
  console.log(`  product_pages: ${pageCount}  (zero-image after the image deletes)`);
  console.log(`  reviews:       ${reviewCount}  (on those pages)`);
  console.log(`  surviving images that reference a to-be-deleted review: ${danglingReviewRefs} (must be 0)`);

  if (danglingReviewRefs > 0) {
    throw new Error("Aborting: a surviving image references a review slated for deletion. Investigate before deleting.");
  }
  if (!apply) {
    console.log(`\nDRY RUN — no DB writes. Re-run with --apply (and FWM_DEV_DB_WRITE_OK).`);
    return;
  }
  requireExplicitWriteFlag();

  // Reversible snapshot of everything we are about to remove (incl. cascade rows).
  const snap = runPsql(
    databaseUrl,
    `select json_build_object(
       'images',            (select coalesce(json_agg(i),'[]') from public.images i where ${IMG_PRED}),
       'image_reports',     (select coalesce(json_agg(r),'[]') from public.image_reports r where r.image_id in (select id from public.images where ${IMG_PRED})),
       'product_pages',     (select coalesce(json_agg(p),'[]') from staging.product_pages p where p.id in (${ZERO_PAGES})),
       'reviews',           (select coalesce(json_agg(rv),'[]') from public.reviews rv where rv.product_page_id in (${ZERO_PAGES})),
       'clothing_type_tags',(select coalesce(json_agg(t),'[]') from staging.product_page_clothing_type_tags t where t.product_page_id in (${ZERO_PAGES})),
       'attribute_tags',    (select coalesce(json_agg(a),'[]') from staging.product_page_attribute_tags a where a.product_page_id in (${ZERO_PAGES}))
     )`,
  ).trim();
  const reportDir = path.join(fwmDataDir(), "_reports");
  await mkdir(reportDir, { recursive: true });
  const stem = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "");
  const snapPath = path.join(reportDir, `orphan_cleanup_${stem}_before.json`);
  await writeFile(snapPath, snap + "\n");
  console.log(`\nReversible snapshot: ${snapPath}`);

  // Single transaction. Images first (frees the page zero-image test), then the
  // reviews on now-zero-image pages, then the pages themselves.
  runPsql(
    databaseUrl,
    `begin;
     delete from public.images where ${IMG_PRED};
     delete from public.reviews where product_page_id in (${ZERO_PAGES});
     delete from staging.product_pages where id in (${ZERO_PAGES});
     commit;`,
  );
  console.log(`\nAPPLIED: deleted ${imgCount} images, ${reviewCount} reviews, ${pageCount} product_pages.`);

  // Refresh search so the removed images drop out of searchable_images.
  try {
    runPsql(databaseUrl, "refresh materialized view concurrently public.searchable_images;");
    console.log(`Refreshed public.searchable_images.`);
  } catch (e) {
    console.log(`WARNING: matview refresh failed (${e.message}). Run: refresh materialized view concurrently public.searchable_images;`);
  }
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
