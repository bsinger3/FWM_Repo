#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevSupabase,
  callSupabaseRest,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

const REQUIRED_RPC_FIELDS = [
  "id",
  "original_url_display",
  "product_page_url_display",
  "monetized_product_url_display",
  "brand",
  "source_site_display",
  "height_in_display",
  "weight_display_display",
  "size_display",
  "color_display",
  "bust_in_number_display",
  "cupsize_display",
  "waist_in",
  "hips_in_display",
  "inseam_inches_display",
  "age_years_display",
  "crop_spec",
  "review_id",
  "product_page_id",
  "full_body_visible",
  "weeks_pregnant",
  "prettiness_score",
];

async function fileText(relativePath) {
  return readFile(path.join(repoRoot, relativePath), "utf8");
}

function has(text, pattern) {
  return pattern instanceof RegExp ? pattern.test(text) : text.includes(pattern);
}

async function verifyLocalEntrypoints() {
  const [indexHtml, indexDevHtml, gitignore] = await Promise.all([
    fileText("index.html"),
    fileText("index.dev.html"),
    fileText(".gitignore"),
  ]);
  const checks = [
    {
      name: "production_index_loads_config_js",
      ok: has(indexHtml, '<script src="./config.js"></script>'),
    },
    {
      name: "production_index_does_not_load_config_dev_js",
      ok: !has(indexHtml, "config.dev.js"),
    },
    {
      name: "dev_index_loads_config_dev_js",
      ok: has(indexDevHtml, '<script src="./config.dev.js"></script>'),
    },
    {
      name: "dev_index_does_not_load_config_js",
      ok: !has(indexDevHtml, '<script src="./config.js"></script>'),
    },
    {
      name: "dev_index_has_dev_assertion",
      ok:
        has(indexDevHtml, 'window.FWM_ENV !== "dev"') &&
        has(indexDevHtml, "https://gosqgqpftqlawvnyelkt.supabase.co"),
    },
    {
      // Crop rendering is a v2 feature that lives only in the dev testbed
      // (index.dev.html). Prod index.html intentionally does NOT carry it yet —
      // it has no crop_spec data and its random query omits the column. Only
      // require the renderer in the dev entrypoint until v2 is promoted to prod.
      name: "crop_renderer_present",
      ok:
        has(indexDevHtml, "function applyCropSpec") &&
        has(indexDevHtml, "applyCropSpec(img, r.crop_spec)"),
    },
    {
      name: "crop_renderer_supports_safe_rotation",
      ok:
        has(indexDevHtml, "rotationCoverScale") &&
        has(indexDevHtml, "[0, 90, 180, 270].includes(normalizedRotation)"),
    },
    {
      // Guard against accidentally porting the crop renderer back into prod
      // before v2 ships. If/when crop rendering is intentionally promoted to
      // index.html, remove this check and re-add index.html to the two above.
      name: "production_index_omits_crop_renderer",
      ok: !has(indexHtml, "applyCropSpec"),
    },
    {
      name: "production_random_query_omits_dev_only_columns",
      ok:
        !has(indexHtml, "crop_spec, review_id, product_page_id") &&
        !has(indexHtml, "prettiness_score"),
    },
    {
      name: "dev_random_query_includes_refresh_columns",
      ok:
        has(indexDevHtml, "crop_spec, review_id, product_page_id") &&
        has(indexDevHtml, "full_body_visible, weeks_pregnant, prettiness_score"),
    },
    {
      name: "dev_entrypoints_ignored",
      ok: has(gitignore, /^config\.dev\.js$/m) && has(gitignore, /^index\.dev\.html$/m),
    },
  ];
  return checks;
}

async function verifyRpcContract(guard) {
  const body = {
    in_clothing_type_id: null,
    in_height: 66,
    in_hips: null,
    in_weight: 140,
    in_bust: null,
    in_cup_size: null,
    in_waist: null,
    require_height: false,
    require_hips: false,
    require_weight: false,
    require_bust: false,
    require_waist: false,
    limit_n: 5,
    offset_n: 0,
  };
  const { data } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "rpc/match_by_measurements",
    method: "POST",
    body,
  });
  const rows = Array.isArray(data) ? data : [];
  const firstRow = rows[0] || {};
  const missingFields = REQUIRED_RPC_FIELDS.filter((field) => !(field in firstRow));
  return {
    request_body: body,
    row_count: rows.length,
    missing_fields: missingFields,
    first_row_field_presence: Object.fromEntries(
      REQUIRED_RPC_FIELDS.map((field) => [field, field in firstRow]),
    ),
    sample_rows: rows.slice(0, 3).map((row) => ({
      id: row.id,
      has_crop_spec: row.crop_spec !== null && row.crop_spec !== undefined,
      has_review_id: Boolean(row.review_id),
      has_product_page_id: Boolean(row.product_page_id),
      full_body_visible: row.full_body_visible,
      weeks_pregnant: row.weeks_pregnant,
      prettiness_score: row.prettiness_score,
      product_page_url_display: row.product_page_url_display,
    })),
  };
}

async function verifyDevTables(guard) {
  const checks = [];
  for (const table of ["search_events", "product_card_events"]) {
    try {
      const { response } = await callSupabaseRest({
        supabaseUrl: guard.supabaseUrl,
        serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
        path: table,
        method: "GET",
        searchParams: { select: "id", limit: "1" },
        prefer: "count=exact",
      });
      checks.push({
        name: `${table}_available`,
        ok: true,
        count: Number((response.headers.get("content-range") || "").split("/").at(-1)),
      });
    } catch (error) {
      checks.push({
        name: `${table}_available`,
        ok: false,
        error: String(error?.message || error),
      });
    }
  }
  return checks;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Dev preview contract guard" });

  const generatedAt = new Date().toISOString();
  const localChecks = await verifyLocalEntrypoints();
  const rpc = await verifyRpcContract(guard);
  const tableChecks = await verifyDevTables(guard);
  const report = {
    generated_at: generatedAt,
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    local_checks: localChecks,
    table_checks: tableChecks,
    rpc,
    passed:
      localChecks.every((check) => check.ok) &&
      tableChecks.every((check) => check.ok) &&
      rpc.row_count > 0 &&
      rpc.missing_fields.length === 0,
  };

  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_preview_contract_verify_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote dev preview contract report: ${reportPath}`);
  console.log(`Local checks: ${localChecks.filter((check) => check.ok).length}/${localChecks.length}`);
  console.log(`Table checks: ${tableChecks.filter((check) => check.ok).length}/${tableChecks.length}`);
  console.log(`RPC sample rows: ${rpc.row_count}`);
  console.log(`RPC missing fields: ${rpc.missing_fields.join(", ") || "none"}`);
  console.log(`Passed: ${report.passed}`);
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
