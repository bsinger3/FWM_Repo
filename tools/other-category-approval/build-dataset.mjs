#!/usr/bin/env node
/**
 * Build the dataset for the "other"-category approval dashboard.
 *
 * Pulls every staging.product_pages row on DEV that is still bucketed as
 * mother_category_id = 'other' (the catch-all clothing bucket), along with all
 * the taxonomy signal we have for it (product name, brand, raw category,
 * breadcrumb, observed clothing-type ids, URL/slug). For each row it runs the
 * project's canonical extractTaxonomy() rules to propose a SUGGESTED mother
 * category other than 'other' (deterministic, no web fetches).
 *
 * Read-only: queries dev, writes a local JSON dataset into this tool's data
 * dir (in the repo, never Downloads). Refuses any non-dev Supabase.
 *
 *   node tools/other-category-approval/build-dataset.mjs
 */

import { execFileSync } from "node:child_process";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  printGuardSummary,
} from "../../scripts/lib/dev-supabase-guard.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "../../scripts/lib/postgres-client.mjs";
import { extractTaxonomy, stripTags } from "../../scripts/audit-dev-product-page-taxonomy.mjs";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.join(toolDir, "data");
const datasetPath = path.join(dataDir, "other-category-dataset.json");
// Reviewed/LLM suggestions, keyed by product_page_id. Auditable + editable;
// merged over the deterministic extractTaxonomy() guess when present.
const suggestionsPath = path.join(dataDir, "llm-suggestions.json");
const repoRoot = path.resolve(toolDir, "..", "..");

// Mother ids extractTaxonomy can emit that are NOT valid FK targets — fold them.
const MOTHER_FOLD = new Map([["romper", "jumpsuits"]]);

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

function urlSlug(url) {
  try {
    const parsed = new URL(url);
    return stripTags(
      decodeURIComponent(parsed.pathname)
        .replace(/[-_/]+/g, " ")
        .replace(/([a-z])\d+(?=\s|$)/gi, "$1"),
    );
  } catch {
    return "";
  }
}

function fieldsForRow(row) {
  return {
    title: stripTags(row.product_title_raw || ""),
    json_ld_product_core: "",
    breadcrumb: stripTags(row.category_breadcrumb_path || ""),
    url_slug: urlSlug(row.normalized_product_page_url),
    json_ld_product_description: "",
    description: "",
    workbook_fallback: stripTags(
      [row.product_category_raw, ...(row.observed_clothing_type_ids || []).filter((t) => t !== "other")]
        .filter(Boolean)
        .join(" "),
    ),
  };
}

async function main() {
  const guard = await assertApprovedDevSupabase();
  printGuardSummary(guard, { prefix: "other-category-approval:build" });
  const databaseUrl = process.env.DEV_DATABASE_URL;
  assertApprovedDevDatabaseUrl(databaseUrl);

  // Authoritative mother vocab (FK target) for the dashboard dropdown.
  const categories = runPsql(
    databaseUrl,
    "select id from staging.clothing_mother_categories order by id;",
  )
    .trim()
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  const rows = JSON.parse(
    runPsql(
      databaseUrl,
      `select coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb) from (
         select id::text, normalized_product_page_url, source_site, brand,
                product_title_raw, product_category_raw, category_breadcrumb_path,
                observed_clothing_type_ids, mother_category_id, category_confidence,
                category_evidence, category_source_field, image_row_count
         from staging.product_pages
         where mother_category_id = 'other'
         order by source_site, normalized_product_page_url
       ) t;`,
    ).trim() || "[]",
  );

  let reviewed = {};
  if (existsSync(suggestionsPath)) {
    reviewed = JSON.parse(await readFile(suggestionsPath, "utf8"));
  }

  const items = rows.map((row) => {
    const taxonomy = extractTaxonomy(fieldsForRow(row));
    const primary = taxonomy.primaryCategory;
    let suggested = primary?.mother_category_id || null;
    if (suggested && MOTHER_FOLD.has(suggested)) suggested = MOTHER_FOLD.get(suggested);
    // Only suggest a REAL category other than 'other'.
    if (suggested === "other" || !categories.includes(suggested)) suggested = null;
    const itemTag = (taxonomy.itemTags || [])[0];

    let suggestedType = itemTag?.clothing_type_id || null;
    let suggestedConfidence = suggested ? primary?.category_confidence || null : null;
    let suggestedSource = suggested ? "rules:extractTaxonomy" : null;
    let suggestedEvidence = suggested ? String(primary?.category_evidence || "").slice(0, 200) : null;

    // Prefer the reviewed suggestion when one exists for this row.
    const r = reviewed[row.id];
    if (r) {
      const m = r.suggested_mother_category_id;
      suggested = m && categories.includes(m) ? m : null;
      suggestedType = r.suggested_clothing_type_id || null;
      suggestedConfidence = r.suggested_confidence || null;
      suggestedSource = r.suggested_by || "reviewed";
      suggestedEvidence = r.suggested_evidence || null;
    }

    return {
      product_page_id: row.id,
      url: row.normalized_product_page_url,
      source_site: row.source_site,
      brand: row.brand || null,
      product_title: row.product_title_raw || null,
      product_category_raw: row.product_category_raw || null,
      category_breadcrumb_path: row.category_breadcrumb_path || null,
      observed_clothing_type_ids: row.observed_clothing_type_ids || [],
      url_slug: urlSlug(row.normalized_product_page_url),
      image_row_count: row.image_row_count || 0,
      current_mother_category_id: row.mother_category_id,
      suggested_mother_category_id: suggested,
      suggested_clothing_type_id: suggestedType,
      suggested_confidence: suggestedConfidence,
      suggested_source: suggestedSource,
      suggested_evidence: suggestedEvidence,
    };
  });

  const withSuggestion = items.filter((i) => i.suggested_mother_category_id).length;
  await mkdir(dataDir, { recursive: true });
  await writeFile(
    datasetPath,
    JSON.stringify(
      {
        generated_at: new Date().toISOString(),
        dev_ref: guard.projectRef,
        source: "staging.product_pages where mother_category_id = 'other'",
        categories,
        total: items.length,
        with_suggestion: withSuggestion,
        items,
      },
      null,
      2,
    ) + "\n",
    "utf8",
  );

  console.log(`\nWrote ${items.length} 'other' rows → ${path.relative(repoRoot, datasetPath)}`);
  console.log(`  ${withSuggestion} have a suggested category; ${items.length - withSuggestion} need manual pick.`);
  const bySuggestion = {};
  for (const i of items) {
    const k = i.suggested_mother_category_id || "(none)";
    bySuggestion[k] = (bySuggestion[k] || 0) + 1;
  }
  console.log("  suggested distribution:");
  for (const [k, v] of Object.entries(bySuggestion).sort((a, b) => b[1] - a[1])) {
    console.log(`    ${String(v).padStart(4)}  ${k}`);
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
