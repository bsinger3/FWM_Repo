#!/usr/bin/env node
/**
 * Build the flagged-image-review dataset.
 *
 * Reporters use the 🚩 button on the live site (index.html, prod Supabase) and on
 * the dev preview (index.dev.html, dev Supabase). Each click inserts a row into
 * `public.image_reports` (image_id, reason, anon_id, created_at). The two
 * environments have SEPARATE report tables, so to review every flag in one place
 * we read BOTH and union them by image_id.
 *
 * Reads:
 *   - PROD_DATABASE_URL  → image_reports (READ-ONLY; guarded to the prod ref)
 *   - DEV_DATABASE_URL   → image_reports + image preview fields (guarded to dev ref)
 *
 * We only ever ACT on dev, so the preview fields (url, comment, source, ...) are
 * pulled from the dev `images` row. Every prod-flagged image_id is matched against
 * dev images; any id missing from dev is still listed but marked not-actionable.
 *
 * Writes (local to the repo, never Downloads):
 *   tools/flagged-image-review/data/flagged-dataset.json
 *
 * Read-only. No writes to either database.
 */
import { spawnSync } from "node:child_process";
import { writeFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadDotEnv } from "../../scripts/lib/local-env.mjs";
import {
  assertProductionDatabaseUrl,
  assertApprovedDevDatabaseUrl,
} from "../../scripts/lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "../../scripts/lib/postgres-client.mjs";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(toolDir, "data");
const outPath = path.join(dataDir, "flagged-dataset.json");
const repoRoot = path.resolve(toolDir, "../..");

await loadDotEnv({ cwd: repoRoot });

function runJson(databaseUrl, sql) {
  const conn = postgresConnectionArgs(databaseUrl);
  const r = spawnSync(
    postgresClientTool("psql"),
    [...conn.args, "-tA", "-v", "ON_ERROR_STOP=1", "-c", sql],
    { encoding: "utf8", env: { ...process.env, ...conn.env }, maxBuffer: 1024 * 1024 * 64 },
  );
  if (r.status !== 0) {
    throw new Error(String(r.stderr || "psql failed").replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
  const out = r.stdout.trim();
  return out ? JSON.parse(out) : null;
}

// Preview fields pulled from the dev images row (what the reviewer sees per card).
const IMG_COLS = [
  "original_url_display",
  "product_page_url_display",
  "monetized_product_url_display",
  "source_site_display",
  "user_comment",
  "size_display",
  "brand",
  "color_display",
  "clothing_type_id",
  "height_in_display",
  "weight_lbs_display",
  "prettiness_score",
  "full_body_visible",
];

function fetchReports(databaseUrl, origin) {
  const rows = runJson(
    databaseUrl,
    `select coalesce(json_agg(json_build_object(
        'image_id', image_id,
        'reason', reason,
        'created_at', created_at
      ) order by created_at desc nulls last), '[]'::json)
     from public.image_reports;`,
  ) || [];
  return rows.map((r) => ({ ...r, origin }));
}

function main() {
  const prodUrl = process.env.PROD_DATABASE_URL;
  const devUrl = process.env.DEV_DATABASE_URL;
  assertProductionDatabaseUrl(prodUrl);
  assertApprovedDevDatabaseUrl(devUrl);

  console.log("Reading prod image_reports (read-only)...");
  const prodReports = fetchReports(prodUrl, "prod");
  console.log(`  prod: ${prodReports.length} reports`);

  console.log("Reading dev image_reports...");
  const devReports = fetchReports(devUrl, "dev");
  console.log(`  dev:  ${devReports.length} reports`);

  const allReports = [...prodReports, ...devReports];
  const flaggedIds = [...new Set(allReports.map((r) => r.image_id))];
  console.log(`Distinct flagged images: ${flaggedIds.length}`);

  // Pull the dev images row for every flagged id (only ids present in dev are actionable).
  const hasRemovedCol = !!runJson(
    devUrl,
    `select to_jsonb(count(*) > 0) from information_schema.columns
     where table_schema='public' and table_name='images' and column_name='removed_at';`,
  );
  const selectCols = ["id", ...IMG_COLS, ...(hasRemovedCol ? ["removed_at", "removed_reason"] : [])];
  const idList = flaggedIds.map((id) => `'${id}'`).join(",");
  const images = idList
    ? runJson(
        devUrl,
        `select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
           select ${selectCols.join(", ")} from public.images where id in (${idList})
         ) t;`,
      )
    : [];
  const imageById = new Map(images.map((row) => [row.id, row]));

  // Assemble one entry per flagged image, carrying all of its reports.
  const reportsByImage = new Map();
  for (const rep of allReports) {
    if (!reportsByImage.has(rep.image_id)) reportsByImage.set(rep.image_id, []);
    reportsByImage.get(rep.image_id).push({ origin: rep.origin, reason: rep.reason, created_at: rep.created_at });
  }

  const entries = flaggedIds.map((id) => {
    const reports = reportsByImage.get(id) || [];
    const image = imageById.get(id) || null;
    const reasons = [...new Set(reports.map((r) => r.reason))];
    const origins = [...new Set(reports.map((r) => r.origin))];
    return {
      image_id: id,
      in_dev_images: !!image,
      report_count: reports.length,
      reasons,
      origins,
      reports: reports.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))),
      image,
      already_removed: !!(image && image.removed_at),
    };
  });

  // Sort: most-reported first, then not-helpful flags ahead of others.
  entries.sort((a, b) => {
    const aHelp = a.reasons.includes("image_not_helpful") ? 1 : 0;
    const bHelp = b.reasons.includes("image_not_helpful") ? 1 : 0;
    if (bHelp !== aHelp) return bHelp - aHelp;
    return b.report_count - a.report_count;
  });

  const dataset = {
    generatedAt: new Date().toISOString(),
    counts: {
      prodReports: prodReports.length,
      devReports: devReports.length,
      flaggedImages: flaggedIds.length,
      presentInDev: entries.filter((e) => e.in_dev_images).length,
      missingFromDev: entries.filter((e) => !e.in_dev_images).length,
    },
    reasonLabels: {
      image_not_helpful: "Image not helpful",
      dead_link: "Dead link",
      duplicate_image: "Duplicate image",
      incorrect_data: "Incorrect measurements/category/size",
      sold_out: "Sold out",
      other_link_problem: "Other link problem",
    },
    entries,
  };

  if (!existsSync(dataDir)) mkdirSync(dataDir, { recursive: true });
  writeFileSync(outPath, JSON.stringify(dataset, null, 2));
  console.log(`\nWrote ${entries.length} flagged images → ${path.relative(repoRoot, outPath)}`);
  console.log(`  present in dev: ${dataset.counts.presentInDev} | missing from dev: ${dataset.counts.missingFromDev}`);
}

main();
