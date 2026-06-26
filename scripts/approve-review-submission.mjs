#!/usr/bin/env node

// Promote user-submitted reviews from the holding-pen table into the live data
// tables in the DEV Supabase database.
//
// Source:  public.user_review_submissions  (status='pending', applied as dev_31)
// Targets: staging.product_pages (find-or-create by normalized url),
//          public.reviews (one row), public.images (one row per uploaded photo,
//          flagged is_fwm_user_content=true), then a refresh of the
//          public.searchable_images materialized view so the new images surface
//          in search.
//
// DEV ONLY. Connects through the same dev guard + DEV_DATABASE_URL libpq psql
// path the other dev-write scripts use. Dry-run by default; --apply requires
// FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev. All of an approve's writes
// run inside one transaction so a partial failure rolls back. A reversible
// snapshot of the submission row is written to FWM_Data/_reports before mutating.
//
// Subcommands:
//   list                                  # read-only; prints pending submissions
//   approve <submission_id> [--apply]     # promote one submission
//   reject  <submission_id> --reason "…" [--apply]   # mark rejected, no live rows
//
//   node scripts/approve-review-submission.mjs list
//   node scripts/approve-review-submission.mjs approve <id>            # dry run
//   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
//     node scripts/approve-review-submission.mjs approve <id> --apply

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

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const argv = process.argv.slice(2);
const apply = argv.includes("--apply");
const REVIEW_UPLOADS_BUCKET = "review-uploads";

// Repo convention for SQL literals (see backfill-dev-image-dimensions.mjs et al).
const sqlString = (v) => (v == null || v === "" ? "null" : `'${String(v).replaceAll("'", "''")}'`);
const sqlNum = (v) => (v == null || v === "" || Number.isNaN(Number(v)) ? "null" : String(Number(v)));
const sqlBool = (v) => (v == null ? "null" : v ? "true" : "false");

function parseArg(name, fallback = null) {
  const prefix = `--${name}=`;
  const eq = argv.find((a) => a.startsWith(prefix));
  if (eq) return eq.slice(prefix.length);
  const idx = argv.indexOf(`--${name}`);
  if (idx !== -1 && idx + 1 < argv.length && !argv[idx + 1].startsWith("--")) return argv[idx + 1];
  return fallback;
}

function runPsql(databaseUrl, sql) {
  const c = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...c.env }, maxBuffer: 1024 * 1024 * 100 },
    );
  } catch (e) {
    throw new Error(String(e.stderr || e.message || "").replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

// Fetch one submission row as JSON (or null if not found).
function fetchSubmission(databaseUrl, id) {
  const out = runPsql(
    databaseUrl,
    `select to_json(s) from public.user_review_submissions s where s.id = ${sqlString(id)};`,
  ).trim();
  return out ? JSON.parse(out) : null;
}

async function cmdList(databaseUrl) {
  const out = runPsql(
    databaseUrl,
    `select coalesce(json_agg(json_build_object(
        'id', s.id,
        'submitted_at', s.submitted_at,
        'brand', s.brand,
        'size_purchased', s.size_purchased,
        'num_photos', coalesce(array_length(s.image_paths, 1), 0)
      ) order by s.submitted_at desc), '[]')
     from public.user_review_submissions s where s.status = 'pending';`,
  ).trim();
  const rows = JSON.parse(out || "[]");
  if (rows.length === 0) {
    console.log("No pending submissions.");
    return;
  }
  console.log(`Pending submissions (${rows.length}):\n`);
  for (const r of rows) {
    console.log(
      `  ${r.id}  ${r.submitted_at}  brand=${r.brand ?? "—"}  size=${r.size_purchased ?? "—"}  photos=${r.num_photos}`,
    );
  }
}

// Build the PUBLIC storage URL for an uploaded object.
function publicUrlFor(supabaseUrl, storagePath) {
  const clean = String(storagePath).replace(/^\/+/, "");
  return `${supabaseUrl}/storage/v1/object/public/${REVIEW_UPLOADS_BUCKET}/${clean}`;
}

async function writeSnapshot(submission, label) {
  const reportDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportDir, { recursive: true });
  const stem = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "");
  const snapPath = path.join(reportDir, `review_submission_${label}_${submission.id}_${stem}_before.json`);
  await writeFile(snapPath, JSON.stringify(submission, null, 2) + "\n");
  return snapPath;
}

async function cmdApprove(guard, databaseUrl, id) {
  if (!id) throw new Error("Usage: approve <submission_id> [--apply]");
  const submission = fetchSubmission(databaseUrl, id);
  if (!submission) throw new Error(`No submission found with id ${id}.`);
  if (submission.status !== "pending") {
    throw new Error(
      `Submission ${id} is status='${submission.status}', not 'pending'. Refusing to re-promote.` +
        (submission.promoted_review_id ? ` (already promoted_review_id=${submission.promoted_review_id})` : ""),
    );
  }

  const imagePaths = Array.isArray(submission.image_paths) ? submission.image_paths : [];
  if (!submission.size_purchased) {
    throw new Error(
      `Submission ${id} has no size_purchased, but public.images.size_display is NOT NULL. Reject it or fix the size first.`,
    );
  }
  if (!submission.product_page_url) {
    throw new Error(`Submission ${id} has no product_page_url; cannot resolve a product page.`);
  }
  if (imagePaths.length === 0) {
    console.log(
      `WARNING: submission ${id} has no image_paths — a review row will be created but no image rows (nothing will surface in search).`,
    );
  }

  // Stable, idempotent review identity (reviews.review_identity_key is UNIQUE).
  const reviewIdentityKey = `user_submission:${submission.id}`;
  // Refuse if a prior partial run already left a review with this key.
  const existingReview = runPsql(
    databaseUrl,
    `select id from public.reviews where review_identity_key = ${sqlString(reviewIdentityKey)};`,
  ).trim();
  if (existingReview) {
    throw new Error(
      `A review with identity key '${reviewIdentityKey}' already exists (id=${existingReview}). ` +
        `Submission status may be out of sync — investigate before re-promoting.`,
    );
  }

  console.log(`\nWould promote submission ${id}:`);
  console.log(`  brand=${submission.brand ?? "—"}  size=${submission.size_purchased}  photos=${imagePaths.length}`);
  console.log(`  product_page_url=${submission.product_page_url}`);
  console.log(`  reviewer_name=${submission.reviewer_name ?? "—"}  source_site=${submission.source_site ?? "—"}`);
  console.log(`  review_identity_key=${reviewIdentityKey}`);
  for (const p of imagePaths) console.log(`    image -> ${publicUrlFor(guard.supabaseUrl, p)}`);

  if (!apply) {
    console.log(`\nDRY RUN — no DB writes. Re-run with --apply (and FWM_DEV_DB_WRITE_OK) to commit.`);
    return;
  }
  requireExplicitWriteFlag();

  const snapPath = await writeSnapshot(submission, "approve");
  console.log(`\nReversible snapshot: ${snapPath}`);

  // --- build the single-transaction promotion SQL ---------------------------
  // 1. find-or-create product page (UNIQUE normalized_product_page_url).
  // 2. insert one review.
  // 3. insert one image per storage path.
  // 4. mark submission approved + back-link promoted ids.
  // Uses CTEs + DO-block-free chained INSERTs threaded through a temp setting so
  // ids generated server-side flow forward without a round-trip.
  const subId = sqlString(submission.id);
  const normalizedUrlExpr = `staging.normalize_product_url(${sqlString(submission.product_page_url)})`;

  // Per-image VALUES rows. original_url_display is the PUBLIC storage URL.
  const imageValues = imagePaths
    .map((p) => {
      const publicUrl = publicUrlFor(guard.supabaseUrl, p);
      return `(
        gen_random_uuid(),
        (select id from page),
        (select id from review),
        ${subId},
        true,
        ${sqlString(publicUrl)},
        ${sqlString(submission.product_page_url)},
        ${sqlNum(submission.height_in_total)},
        ${sqlNum(submission.weight_lbs)},
        ${sqlNum(submission.bra_band_in)},
        ${sqlNum(submission.bust_full_in)},
        ${submission.bust_in_number == null ? "null" : String(parseInt(submission.bust_in_number, 10))},
        ${sqlString(submission.cup_size)},
        ${sqlNum(submission.waist_in) === "null" ? "null" : sqlString(submission.waist_in)},
        ${sqlNum(submission.hips_in)},
        ${sqlNum(submission.inseam_in)},
        ${submission.age_years == null ? "null" : String(parseInt(submission.age_years, 10))},
        ${submission.weeks_pregnant == null ? "null" : String(parseInt(submission.weeks_pregnant, 10))},
        ${sqlBool(submission.full_body_visible)},
        ${sqlString(submission.brand)},
        ${sqlString(submission.source_site)},
        ${sqlString(submission.size_purchased)},
        ${sqlString(submission.color)},
        ${sqlString(submission.mother_category_id)},
        ${sqlString(submission.reviewer_name)},
        ${sqlString(submission.user_comment)}
      )`;
    })
    .join(",\n");

  // images.waist_in is text in this schema; pass the numeric as text.
  const imageInsert = imagePaths.length
    ? `, ins_images as (
        insert into public.images (
          id, product_page_id, review_id, user_submission_id, is_fwm_user_content,
          original_url_display, product_page_url_display,
          height_in_display, weight_lbs_display, bra_band_in_display, bust_in_display,
          bust_in_number_display, cupsize_display, waist_in, hips_in_display,
          inseam_inches_display, age_years_display, weeks_pregnant, full_body_visible,
          brand, source_site_display, size_display, color_display, mother_category_id,
          reviewer_name_raw, user_comment
        )
        values
        ${imageValues}
        returning id
      )`
    : "";

  const imageCountSelect = imagePaths.length
    ? `(select count(*) from ins_images)`
    : `0`;

  const transactionSql = `
begin;

with page as (
  insert into staging.product_pages (
    normalized_product_page_url, brand, source_site, mother_category_id,
    category_confidence, needs_manual_review, populated_from
  )
  values (
    ${normalizedUrlExpr}, ${sqlString(submission.brand)}, ${sqlString(submission.source_site)},
    ${sqlString(submission.mother_category_id)}, 'low', true, 'user_submission'
  )
  on conflict (normalized_product_page_url) do update
    set updated_at = now()
  returning id
),
review as (
  insert into public.reviews (
    product_page_id, normalized_product_page_url, review_identity_key,
    source_site, reviewer_name_raw, user_comment, source_file
  )
  values (
    (select id from page),
    ${normalizedUrlExpr},
    ${sqlString(reviewIdentityKey)},
    ${sqlString(submission.source_site)},
    ${sqlString(submission.reviewer_name)},
    ${sqlString(submission.user_comment)},
    ${sqlString(`user_review_submissions:${submission.id}`)}
  )
  returning id
)${imageInsert},
upd as (
  update public.user_review_submissions
    set status = 'approved',
        reviewed_at = now(),
        promoted_review_id = (select id from review),
        promoted_product_page_id = (select id from page)
    where id = ${subId} and status = 'pending'
  returning id
)
select
  (select id from page)   as product_page_id,
  (select id from review) as review_id,
  ${imageCountSelect}     as image_count,
  (select count(*) from upd) as submissions_updated;

commit;`;

  const result = runPsql(databaseUrl, transactionSql).trim();
  // The SELECT row is page_id|review_id|image_count|submissions_updated (4 fields).
  // psql also prints command-status tags (BEGIN/COMMIT) with --tuples-only, so we
  // can't just take the last line — pick the line that has the 4 pipe-delimited
  // fields instead.
  const line =
    result
      .split("\n")
      .map((s) => s.trim())
      .filter((l) => l.split("|").length === 4)
      .pop() || "";
  const [productPageId, reviewId, imageCount, submissionsUpdated] = line.split("|");

  if (Number(submissionsUpdated) !== 1) {
    // The transaction committed already; surface loudly so the operator checks.
    console.log(
      `WARNING: expected to update exactly 1 submission, updated ${submissionsUpdated}. Inspect submission ${id}.`,
    );
  }

  console.log(`\nAPPLIED:`);
  console.log(`  product_page_id = ${productPageId}`);
  console.log(`  review_id       = ${reviewId}`);
  console.log(`  images inserted = ${imageCount}`);
  console.log(`  submission ${id} -> status='approved'`);

  // Refresh search so the new user-content images appear.
  if (Number(imageCount) > 0) {
    try {
      runPsql(databaseUrl, "refresh materialized view concurrently public.searchable_images;");
      console.log(`  Refreshed public.searchable_images.`);
    } catch (e) {
      console.log(
        `  WARNING: matview refresh failed (${e.message}). Run: refresh materialized view concurrently public.searchable_images;`,
      );
    }
  } else {
    console.log(`  No images inserted; skipping searchable_images refresh.`);
  }
}

async function cmdReject(databaseUrl, id) {
  if (!id) throw new Error('Usage: reject <submission_id> --reason "<text>"');
  const reason = parseArg("reason");
  if (!reason) throw new Error('reject requires --reason "<text>".');
  const submission = fetchSubmission(databaseUrl, id);
  if (!submission) throw new Error(`No submission found with id ${id}.`);
  if (submission.status !== "pending") {
    throw new Error(`Submission ${id} is status='${submission.status}', not 'pending'. Refusing to reject.`);
  }

  console.log(`\nWould reject submission ${id} with reason: ${reason}`);
  console.log(`  (No live rows are created. Orphaned storage objects can be cleaned up later — not deleted here.)`);

  if (!apply) {
    console.log(`\nDRY RUN — no DB writes. Re-run with --apply (and FWM_DEV_DB_WRITE_OK) to commit.`);
    return;
  }
  requireExplicitWriteFlag();

  const snapPath = await writeSnapshot(submission, "reject");
  console.log(`\nReversible snapshot: ${snapPath}`);

  const out = runPsql(
    databaseUrl,
    `update public.user_review_submissions
       set status = 'rejected', reviewed_at = now(), rejection_reason = ${sqlString(reason)}
     where id = ${sqlString(id)} and status = 'pending'
     returning id;`,
  ).trim();
  if (!out) throw new Error(`Reject affected 0 rows for ${id} (status may have changed concurrently).`);
  console.log(`\nAPPLIED: submission ${id} -> status='rejected'.`);
}

async function main() {
  const sub = argv.find((a) => !a.startsWith("--"));
  if (!sub || !["list", "approve", "reject"].includes(sub)) {
    console.log("Usage:");
    console.log("  node scripts/approve-review-submission.mjs list");
    console.log("  node scripts/approve-review-submission.mjs approve <submission_id> [--apply]");
    console.log('  node scripts/approve-review-submission.mjs reject <submission_id> --reason "<text>" [--apply]');
    process.exit(sub ? 1 : 0);
  }

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: false });
  printGuardSummary(guard, { prefix: "approve-review-submission" });
  const databaseUrl = process.env.DEV_DATABASE_URL;
  assertApprovedDevDatabaseUrl(databaseUrl);

  // The submission id is the first non-flag arg after the subcommand.
  const positional = argv.filter((a) => !a.startsWith("--"));
  const id = positional[1];

  if (sub === "list") return cmdList(databaseUrl);
  if (sub === "approve") return cmdApprove(guard, databaseUrl, id);
  if (sub === "reject") return cmdReject(databaseUrl, id);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
