#!/usr/bin/env node
// Restore review text into dev public.images / public.reviews user_comment for the
// ~9,693 rows where an off-by-one column shift (2026-06-16 dev seed) put the source
// CSV path into user_comment and dropped the real comment.
//
// The recovered text comes from the source intake CSVs (joined by review_row_key),
// produced by tools-side recovery into:
//   FWM_Data/_reports/corrupted_user_comment_recovery.json
// That file also carries the OLD (corrupted) value per row, so this is reversible.
//
// SAFETY: dev-only (refuses non-dev URLs); only touches rows whose CURRENT
// user_comment still looks like a path (so we never clobber an already-fixed or
// legitimate comment). Dry-run unless --apply AND FWM_DEV_DB_WRITE_OK are set.
// Touches ONLY public.images + public.reviews; never product_pages.
//
// Usage:
//   node scripts/restore-dev-corrupted-user-comments.mjs                 # dry-run
//   FWM_DEV_DB_WRITE_OK=yes-i-understand-this-is-dev \
//   node scripts/restore-dev-corrupted-user-comments.mjs --apply         # write dev

import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  callSupabaseRest,
  requireExplicitWriteFlag,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs } from "./lib/postgres-client.mjs";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const reportPath = path.join(fwmDataDir(repoRoot), "_reports", "corrupted_user_comment_recovery.json");

function looksLikePath(v) {
  const s = String(v || "");
  return s.startsWith("/Users/") || s.trim().endsWith(".csv");
}

// Pull the rows that are STILL corrupted right now (id + review_id), so we only
// update genuinely-corrupted rows and skip anything already fixed.
async function fetchCurrentlyCorrupted(guard) {
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const rows = [];
  let offset = 0;
  for (;;) {
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey,
      path: "images",
      searchParams: {
        select: "id,review_id,user_comment",
        or: "(user_comment.like./Users/*,user_comment.like.*.csv)",
        order: "id.asc",
        limit: "1000",
        offset: String(offset),
      },
    });
    if (!Array.isArray(data) || data.length === 0) break;
    rows.push(...data);
    offset += data.length;
    if (data.length < 1000) break;
  }
  return rows;
}

function runPsqlBatches(databaseUrl, statements) {
  const connection = postgresConnectionArgs(databaseUrl);
  return new Promise((resolve, reject) => {
    const psql = postgresClientTool("psql");
    const proc = spawn(psql, [...connection.args, "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"], {
      stdio: ["pipe", "inherit", "inherit"],
      env: { ...process.env, ...connection.env },
    });
    proc.on("error", reject);
    proc.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`psql exited ${code}`))));
    proc.stdin.write("BEGIN;\n");
    for (const sql of statements) proc.stdin.write(sql);
    proc.stdin.write("COMMIT;\n");
    proc.stdin.end();
  });
}

// Dollar-quote tag chosen so it cannot appear inside JSON-escaped review text.
const TAG = "$fwmrestore$";

function updateImagesSql(batch) {
  const json = JSON.stringify(batch.map((r) => ({ id: r.id, c: r.recovered_comment })));
  return (
    `UPDATE public.images img SET user_comment = v.c\n` +
    `FROM jsonb_to_recordset(${TAG}${json}${TAG}::jsonb) AS v(id uuid, c text)\n` +
    `WHERE img.id = v.id;\n`
  );
}

function updateReviewsSql(entries) {
  const json = JSON.stringify(entries.map(([id, c]) => ({ id, c })));
  return (
    `UPDATE public.reviews rv SET user_comment = v.c\n` +
    `FROM jsonb_to_recordset(${TAG}${json}${TAG}::jsonb) AS v(id uuid, c text)\n` +
    `WHERE rv.id = v.id;\n`
  );
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "restore-user-comments" });

  const report = JSON.parse(await readFile(reportPath, "utf8"));
  const recoveredById = new Map(report.images.map((r) => [r.id, r]));
  const reviewMap = report.reviews; // review_id -> recovered comment

  console.log(`Recovery report: ${report.image_count} images, ${report.review_count} reviews.`);
  console.log("Fetching rows still corrupted in dev…");
  const current = await fetchCurrentlyCorrupted(guard);
  console.log(`Currently corrupted in dev: ${current.length}`);

  // Only update rows that (a) are still corrupted now AND (b) have a recovered
  // comment AND (c) the recovered comment is real text (not a path/empty).
  const imageUpdates = [];
  const reviewIds = new Set();
  let skippedNoRecovery = 0;
  let skippedBadRecovery = 0;
  for (const row of current) {
    if (!looksLikePath(row.user_comment)) continue; // safety: only path-comments
    const rec = recoveredById.get(row.id);
    if (!rec) { skippedNoRecovery++; continue; }
    const text = rec.recovered_comment;
    if (looksLikePath(text) || !String(text).trim()) { skippedBadRecovery++; continue; }
    imageUpdates.push({ id: row.id, recovered_comment: text });
    if (row.review_id) reviewIds.add(row.review_id);
  }
  const reviewUpdates = [...reviewIds]
    .map((id) => [id, reviewMap[id]])
    .filter(([, c]) => c != null && !looksLikePath(c) && String(c).trim());

  console.log(`\nPlanned updates:`);
  console.log(`  public.images.user_comment : ${imageUpdates.length}`);
  console.log(`  public.reviews.user_comment: ${reviewUpdates.length}`);
  console.log(`  skipped (no recovery)      : ${skippedNoRecovery}`);
  console.log(`  skipped (bad recovery)     : ${skippedBadRecovery}`);
  if (imageUpdates.length) {
    const s = imageUpdates[0];
    console.log(`\nsample: image ${s.id}\n  -> ${JSON.stringify(String(s.recovered_comment).slice(0, 80))}`);
  }

  if (!apply) {
    console.log("\nDry-run only. No rows written. Re-run with --apply (+ write flag) to update dev.");
    return;
  }
  requireExplicitWriteFlag();
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const statements = [];
  for (let i = 0; i < imageUpdates.length; i += 1000) statements.push(updateImagesSql(imageUpdates.slice(i, i + 1000)));
  for (let i = 0; i < reviewUpdates.length; i += 1000) statements.push(updateReviewsSql(reviewUpdates.slice(i, i + 1000)));

  console.log(`\nApplying to dev (images + reviews) in one transaction…`);
  await runPsqlBatches(process.env.DEV_DATABASE_URL, statements);
  console.log(`Done. Restored user_comment on ${imageUpdates.length} images and ${reviewUpdates.length} reviews.`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
