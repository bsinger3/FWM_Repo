#!/usr/bin/env node

import fs from "node:fs";
import { execFileSync } from "node:child_process";

const DEFAULT_LIMIT = 150;

function decodeHtml(value) {
  return String(value || "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

function textFromHtml(html) {
  return decodeHtml(
    html
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " "),
  );
}

function firstMatch(text, patterns) {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) return decodeHtml(match[1]);
  }
  return null;
}

function asText(value) {
  if (!value) return null;
  if (typeof value === "string") return decodeHtml(value);
  if (typeof value === "object") {
    if (typeof value.name === "string") return decodeHtml(value.name);
    if (typeof value["@id"] === "string") return decodeHtml(value["@id"]);
  }
  return null;
}

function parseJsonLd(html) {
  const blocks = [...html.matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)];
  const objects = [];
  for (const block of blocks) {
    const raw = decodeHtml(block[1]).trim();
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw);
      objects.push(...(Array.isArray(parsed) ? parsed : [parsed]));
    } catch {
      // Many retailer pages have malformed analytics-adjacent JSON-LD. Ignore those.
    }
  }
  return objects.flatMap((object) => {
    if (Array.isArray(object?.["@graph"])) return object["@graph"];
    return [object];
  });
}

function extractMetadata(html, url) {
  const jsonLd = parseJsonLd(html);
  const product = jsonLd.find((item) => {
    const type = item?.["@type"];
    return type === "Product" || (Array.isArray(type) && type.includes("Product"));
  });
  const breadcrumbs = jsonLd.find((item) => {
    const type = item?.["@type"];
    return type === "BreadcrumbList" || (Array.isArray(type) && type.includes("BreadcrumbList"));
  });

  const breadcrumbNames = Array.isArray(breadcrumbs?.itemListElement)
    ? breadcrumbs.itemListElement.map((item) => asText(item?.item) || asText(item)).filter(Boolean)
    : [];

  const ogTitle = firstMatch(html, [
    /<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["'][^>]*>/i,
    /<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:title["'][^>]*>/i,
  ]);
  const documentTitle = firstMatch(html, [/<title[^>]*>([\s\S]*?)<\/title>/i]);
  const productTitle = asText(product?.name) || ogTitle || documentTitle;
  const brand = asText(product?.brand);
  const category =
    asText(product?.category) ||
    firstMatch(html, [
      /<meta[^>]+property=["']product:category["'][^>]+content=["']([^"']+)["'][^>]*>/i,
      /<meta[^>]+name=["']category["'][^>]+content=["']([^"']+)["'][^>]*>/i,
    ]) ||
    breadcrumbNames.at(-1) ||
    null;

  return {
    product_title_raw: productTitle ? cleanTitle(productTitle, url) : null,
    brand,
    product_category_raw: category,
    raw_metadata: {
      enrichment_source: "product_page_html",
      enriched_at: new Date().toISOString(),
      json_ld_product_found: Boolean(product),
      json_ld_breadcrumbs_found: Boolean(breadcrumbs),
      breadcrumb_names: breadcrumbNames,
    },
  };
}

function cleanTitle(title, url) {
  let cleaned = textFromHtml(title)
    .replace(/\s+[|–-]\s+(L\.?L\.?\s*Bean|Rent the Runway|Nuuly).*$/i, "")
    .replace(/\s+\|\s+.*$/i, "")
    .trim();
  if (!cleaned && url) cleaned = url;
  return cleaned || null;
}

function categoryFromText(title, category) {
  const signal = `${title || ""} ${category || ""}`.toLowerCase();
  const rules = [
    ["culottes", "bottoms", "culottes"],
    ["jogger", "bottoms", "joggers"],
    ["sweatpant", "bottoms", "sweatpants"],
    ["corduroy", "bottoms", "corduroy-pants"],
    ["jean", "bottoms", "jeans"],
    ["denim", "bottoms", "jeans"],
    ["pant", "bottoms", "pants"],
    ["trouser", "bottoms", "pants"],
    ["short", "bottoms", "shorts"],
    ["skirt", "bottoms", "skirt"],
    ["overall", "jumpsuits-rompers", "overalls"],
    ["shortall", "jumpsuits-rompers", "overalls"],
    ["coverall", "jumpsuits-rompers", "coveralls"],
    ["jumpsuit", "jumpsuits-rompers", "jumpsuit"],
    ["romper", "jumpsuits-rompers", "romper"],
    ["catsuit", "jumpsuits-rompers", "coveralls"],
    ["dress", "dresses", "dress"],
    ["gown", "dresses", "gown"],
    ["caftan", "dresses", "caftan"],
    ["kaftan", "dresses", "caftan"],
    ["swimsuit", "swimwear", "swimwear"],
    ["bikini", "swimwear", "bikini"],
    ["jacket", "outerwear", "jacket"],
    ["coat", "outerwear", "coat"],
    ["vest", "tops", "vest"],
    ["bustier", "tops", "bustier"],
    ["corset", "tops", "bustier"],
    ["bandeau", "tops", "bustier"],
    ["button", "tops", "button-up"],
    ["halter", "tops", "halter"],
    ["tunic", "tops", "tunic"],
    ["shirt", "tops", "shirt"],
    ["sweatshirt", "tops", "sweatshirt"],
    ["hoodie", "tops", "sweatshirt"],
    ["sweater", "tops", "sweater"],
    ["cardigan", "tops", "cardigan"],
    ["tee", "tops", "tee"],
    ["tank", "tops", "tank"],
    ["top", "tops", "top"],
    ["bra", "intimates", "bra"],
    ["underwear", "intimates", "underwear"],
    ["pajama", "sleepwear", "pajamas"],
  ];
  for (const [needle, mother, raw] of rules) {
    if (signal.includes(needle)) return { mother_category_id: mother, product_category_raw: raw };
  }
  return {};
}

function sqlString(value) {
  if (value === undefined || value === null || value === "") return "null";
  return `'${String(value).replace(/'/g, "''")}'`;
}

function runLinkedQuery(sql) {
  const output = execFileSync("supabase", ["db", "query", "--linked", "-o", "json", sql], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  const parsed = JSON.parse(output);
  return parsed.rows || [];
}

async function main() {
  const limit = Number(process.argv.find((arg) => arg.startsWith("--limit="))?.split("=")[1] || DEFAULT_LIMIT);
  const rows = runLinkedQuery(`
    select
      id,
      normalized_product_page_url,
      product_title_raw,
      product_category_raw,
      mother_category_id,
      brand
    from staging.product_pages
    where
      product_title_raw is null
      or product_category_raw is null
      or mother_category_id is null
    order by image_row_count desc, normalized_product_page_url
    limit ${Number.isFinite(limit) ? Math.max(1, limit) : DEFAULT_LIMIT};
  `);

  let updated = 0;
  let failed = 0;
  const patches = [];
  for (const row of rows) {
    try {
      const response = await fetch(row.normalized_product_page_url, {
        redirect: "follow",
        headers: {
          "user-agent": "FriendsWithMeasurementsStagingEnrichment/1.0 (+product metadata QA)",
          accept: "text/html,application/xhtml+xml",
        },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const html = await response.text();
      const metadata = extractMetadata(html, row.normalized_product_page_url);
      const category = categoryFromText(metadata.product_title_raw, metadata.product_category_raw);
      const patch = {
        id: row.id,
        product_title_raw: row.product_title_raw || metadata.product_title_raw,
        product_category_raw: row.product_category_raw || category.product_category_raw || metadata.product_category_raw,
        mother_category_id: row.mother_category_id || category.mother_category_id || null,
        brand: row.brand || metadata.brand,
        raw_metadata: metadata.raw_metadata,
        category_evidence: category.mother_category_id
          ? `product page metadata: ${metadata.product_title_raw || metadata.product_category_raw}`
          : "product page metadata fetched; still needs taxonomy review",
        category_confidence: category.mother_category_id ? "medium" : "low",
        needs_manual_review: !category.mother_category_id,
        updated_at: new Date().toISOString(),
      };

      patches.push(patch);
      updated += 1;
      console.log(`updated ${updated}/${rows.length}: ${row.normalized_product_page_url}`);
      await new Promise((resolve) => setTimeout(resolve, 350));
    } catch (error) {
      failed += 1;
      console.warn(`failed: ${row.normalized_product_page_url}: ${error.message}`);
    }
  }

  if (patches.length > 0) {
    const values = patches.map((patch) => `(
      ${sqlString(patch.id)}::uuid,
      ${sqlString(patch.product_title_raw)},
      ${sqlString(patch.product_category_raw)},
      ${sqlString(patch.mother_category_id)},
      ${sqlString(patch.brand)},
      ${sqlString(patch.category_evidence)},
      ${sqlString(patch.category_confidence)},
      ${patch.needs_manual_review ? "true" : "false"},
      ${sqlString(JSON.stringify(patch.raw_metadata))}::jsonb,
      ${sqlString(patch.updated_at)}::timestamptz
    )`).join(",\n");
    runLinkedQuery(`
      update staging.product_pages pp
      set
        product_title_raw = coalesce(v.product_title_raw, pp.product_title_raw),
        product_category_raw = coalesce(v.product_category_raw, pp.product_category_raw),
        mother_category_id = coalesce(v.mother_category_id, pp.mother_category_id),
        brand = coalesce(v.brand, pp.brand),
        category_evidence = v.category_evidence,
        category_confidence = v.category_confidence,
        needs_manual_review = v.needs_manual_review,
        raw_metadata = coalesce(pp.raw_metadata, '{}'::jsonb) || v.raw_metadata,
        updated_at = v.updated_at
      from (
        values
        ${values}
      ) as v(
        id,
        product_title_raw,
        product_category_raw,
        mother_category_id,
        brand,
        category_evidence,
        category_confidence,
        needs_manual_review,
        raw_metadata,
        updated_at
      )
      where pp.id = v.id;
    `);
  }

  console.log(JSON.stringify({ scanned: rows.length, updated, failed }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
