#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const limit = Math.max(1, Number(parseArg("limit", "50")) || 50);
const includeChecked = process.argv.includes("--include-checked");
const userAgent = "FWMDevCatalogImageBackfill/0.1 (+https://friendswithmeasurements.com)";

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function timestampStem(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(".", "");
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlTextArray(values) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  return `array[${items.map(sqlString).join(",")}]::text[]`;
}

function runPsql(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      {
        encoding: "utf8",
        env: { ...process.env, ...connection.env },
        maxBuffer: 1024 * 1024 * 50,
      },
    );
  } catch (error) {
    const stderr = String(error.stderr || error.message || "");
    throw new Error(stderr.replaceAll(databaseUrl, redactDatabaseUrl(databaseUrl)));
  }
}

function parseJsonPsql(output) {
  const trimmed = output.trim();
  return trimmed ? JSON.parse(trimmed) : [];
}

function decodeHtml(value) {
  return String(value || "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function firstMatch(regex, text) {
  const match = String(text || "").match(regex);
  return match ? decodeHtml(match[1]).trim() : "";
}

function resolveUrl(value, baseUrl) {
  try {
    return new URL(String(value || "").trim(), baseUrl).href;
  } catch {
    return "";
  }
}

function isLikelyImageUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return /\.(?:avif|gif|jpe?g|png|webp)(?:$|[?#])/i.test(url.pathname);
  } catch {
    return false;
  }
}

function firstLikelyImageUrl(values, baseUrl) {
  return uniqueLikelyImageUrls(values, baseUrl)[0] || "";
}

function uniqueLikelyImageUrls(values, baseUrl) {
  const seen = new Set();
  const urls = [];
  for (const value of values.filter(Boolean)) {
    const resolved = resolveUrl(value, baseUrl);
    if (!isLikelyImageUrl(resolved)) continue;
    const comparable = resolved.replace(/^https?:\/\//, "").replace(/^www\./, "").toLowerCase();
    if (seen.has(comparable)) continue;
    seen.add(comparable);
    urls.push(resolved);
  }
  return urls;
}

function collectImageValues(value, baseUrl, images = []) {
  if (!value) return images;
  if (typeof value === "string") {
    const resolved = resolveUrl(value, baseUrl);
    if (resolved) images.push(resolved);
    return images;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectImageValues(item, baseUrl, images);
    return images;
  }
  if (typeof value === "object") collectImageValues(value.url || value.contentUrl || value.src, baseUrl, images);
  return images;
}

function catalogFromJsonLd(html, baseUrl) {
  const images = [];
  for (const match of String(html || "").matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    try {
      const parsed = JSON.parse(decodeHtml(match[1]).trim());
      const nodes = [];
      collectJsonLdNodes(parsed, nodes);
      for (const node of nodes) {
        const types = (Array.isArray(node?.["@type"]) ? node["@type"] : [node?.["@type"]]).map((type) => String(type || "").toLowerCase());
        if (types.includes("product")) {
          collectImageValues(node.image, baseUrl, images);
          collectImageValues(node.offers?.image, baseUrl, images);
        }
      }
    } catch {
      // Ignore malformed merchant JSON-LD and fall back to meta tags.
    }
  }
  return uniqueLikelyImageUrls(images, baseUrl);
}

function collectJsonLdNodes(value, nodes = []) {
  if (!value || typeof value !== "object") return nodes;
  if (Array.isArray(value)) {
    for (const item of value) collectJsonLdNodes(item, nodes);
    return nodes;
  }
  nodes.push(value);
  if (Array.isArray(value["@graph"])) collectJsonLdNodes(value["@graph"], nodes);
  return nodes;
}

function metaContent(html, property) {
  const escaped = property.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = [
    new RegExp(`<meta[^>]+property=["']${escaped}["'][^>]+content=["']([^"']+)["'][^>]*>`, "i"),
    new RegExp(`<meta[^>]+name=["']${escaped}["'][^>]+content=["']([^"']+)["'][^>]*>`, "i"),
  ];
  for (const pattern of patterns) {
    const value = firstMatch(pattern, html);
    if (value) return value;
  }
  return "";
}

async function shopifyProductPreview(productUrl) {
  try {
    const parsed = new URL(productUrl);
    const productJsonUrl = `${parsed.origin}${parsed.pathname.replace(/\/+$/, "")}.js`;
    const response = await fetch(productJsonUrl, {
      redirect: "follow",
      signal: AbortSignal.timeout(7000),
      headers: { "user-agent": userAgent, accept: "application/json,text/javascript,*/*" },
    });
    if (!response.ok) return null;
    const product = await response.json();
    const catalogImageUrls = uniqueLikelyImageUrls(
      [product.featured_image, product.image, ...(Array.isArray(product.images) ? product.images : [])],
      productJsonUrl,
    );
    return catalogImageUrls.length
      ? {
          catalog_image_url: catalogImageUrls[0],
          catalog_image_urls: catalogImageUrls,
          catalog_image_source: "shopify_product_json",
          catalog_image_fetch_status: "found",
        }
      : null;
  } catch {
    return null;
  }
}

async function catalogPreview(url) {
  let finalUrl = url;
  try {
    const response = await fetch(url, {
      redirect: "follow",
      signal: AbortSignal.timeout(7000),
      headers: { "user-agent": userAgent, accept: "text/html,application/xhtml+xml" },
    });
    finalUrl = response.url || url;
    if (!response.ok) {
      return {
        catalog_image_url: "",
        catalog_image_urls: [],
        catalog_image_source: "",
        catalog_image_fetch_status: `http_status_${response.status}`,
        catalog_image_fetch_error: "",
      };
    }
    const html = await response.text();
    const jsonLdImages = catalogFromJsonLd(html, finalUrl);
    const metaImages = uniqueLikelyImageUrls([metaContent(html, "og:image"), metaContent(html, "twitter:image")], finalUrl);
    const shopify = jsonLdImages.length || metaImages.length ? null : await shopifyProductPreview(url);
    const catalogImageUrls = jsonLdImages.length ? jsonLdImages : metaImages.length ? metaImages : shopify?.catalog_image_urls || [];
    return {
      catalog_image_url: catalogImageUrls[0] || "",
      catalog_image_urls: catalogImageUrls,
      catalog_image_source: jsonLdImages.length ? "json_ld" : metaImages.length ? "meta" : shopify?.catalog_image_source || "",
      catalog_image_fetch_status: catalogImageUrls.length ? "found" : "not_found",
      catalog_image_fetch_error: "",
    };
  } catch (error) {
    const shopify = await shopifyProductPreview(url);
    if (shopify) return shopify;
    return {
      catalog_image_url: "",
      catalog_image_urls: [],
      catalog_image_source: "",
      catalog_image_fetch_status: "error",
      catalog_image_fetch_error: error.message || String(error),
    };
  }
}

function candidateSql() {
  return `
select coalesce(jsonb_agg(row_to_json(candidate) order by normalized_product_page_url), '[]'::jsonb)
from (
  select id::text, normalized_product_page_url, catalog_image_url, catalog_image_urls, catalog_image_fetched_at
  from staging.product_pages
  where normalized_product_page_url is not null
    ${includeChecked ? "" : "and cardinality(catalog_image_urls) = 0"}
  order by catalog_image_fetched_at nulls first, normalized_product_page_url
  limit ${limit}
) candidate;`;
}

function updateSql(results) {
  const rows = results.map((row) => `(
    ${sqlString(row.product_page_id)}::uuid,
    ${sqlString(row.catalog_image_url)},
    ${sqlTextArray(row.catalog_image_urls)},
    ${sqlString(row.catalog_image_source)},
    ${sqlString(row.catalog_image_fetch_status)},
    ${sqlString(row.catalog_image_fetch_error)}
  )`).join(",\n");
  if (!rows) return "";
  return `
update staging.product_pages pp
set
  catalog_image_url = coalesce(nullif(v.catalog_image_url, ''), pp.catalog_image_url),
  catalog_image_urls = case
    when cardinality(v.catalog_image_urls) > 0 then v.catalog_image_urls
    else pp.catalog_image_urls
  end,
  catalog_image_source = coalesce(nullif(v.catalog_image_source, ''), pp.catalog_image_source),
  catalog_image_fetched_at = now(),
  catalog_image_fetch_status = v.catalog_image_fetch_status,
  catalog_image_fetch_error = nullif(v.catalog_image_fetch_error, ''),
  updated_at = now()
from (
  values
  ${rows}
) as v(product_page_id, catalog_image_url, catalog_image_urls, catalog_image_source, catalog_image_fetch_status, catalog_image_fetch_error)
where pp.id = v.product_page_id;`;
}

function summarize(results) {
  const byStatus = {};
  const bySource = {};
  for (const row of results) {
    byStatus[row.catalog_image_fetch_status] = (byStatus[row.catalog_image_fetch_status] || 0) + 1;
    if (row.catalog_image_source) bySource[row.catalog_image_source] = (bySource[row.catalog_image_source] || 0) + 1;
  }
  return {
    scanned_count: results.length,
    found_count: results.filter((row) => row.catalog_image_url).length,
    found_url_count: results.reduce((sum, row) => sum + (row.catalog_image_urls?.length || 0), 0),
    by_status: byStatus,
    by_source: bySource,
  };
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Catalog image backfill guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const candidates = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, candidateSql()));
  const results = [];
  for (const candidate of candidates) {
    const catalog = await catalogPreview(candidate.normalized_product_page_url);
    results.push({
      product_page_id: candidate.id,
      normalized_product_page_url: candidate.normalized_product_page_url,
      ...catalog,
    });
  }
  if (apply) {
    requireExplicitWriteFlag();
    const sql = updateSql(results);
    if (sql) runPsql(process.env.DEV_DATABASE_URL, sql);
  }

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `dev_product_page_catalog_image_backfill_${timestampStem(new Date(generatedAt))}.json`);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    limit,
    include_checked: includeChecked,
    summary: summarize(results),
    results,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(`Wrote catalog image backfill report: ${reportPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Summary: ${JSON.stringify(report.summary)}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
