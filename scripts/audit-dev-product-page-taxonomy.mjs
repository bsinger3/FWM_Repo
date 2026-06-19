#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
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
const onlyUnchecked = !process.argv.includes("--include-checked");
const includeAllProductPages = process.argv.includes("--include-all-product-pages");
const limit = Math.max(1, Number(parseArg("limit", "25")) || 25);
const timeoutMs = Math.max(1000, Number(parseArg("timeout-ms", "10000")) || 10000);
const perDomainDelayMs = Math.max(0, Number(parseArg("per-domain-delay-ms", "1000")) || 1000);
const maxPerDomain = Math.max(1, Number(parseArg("max-per-domain", "2")) || 2);
const userAgent = parseArg("user-agent", "FWMDevProductTaxonomyAudit/0.1 (+https://friendswithmeasurements.com)");
const verifiedReportPath = parseArg("verified-report");
const excludeApprovalReportPaths = parseArgs("exclude-approval-report");
const excludeTaxonomyReportPaths = parseArgs("exclude-taxonomy-report");
const productPageIdsFile = parseArg("product-page-ids-file");
const shardCount = Math.max(1, Number(parseArg("shard-count", "1")) || 1);
const shardIndex = Math.max(0, Number(parseArg("shard-index", "0")) || 0);
const robotsUrlFallback = process.argv.includes("--robots-url-fallback");
const amazonBrowserFallback = process.argv.includes("--amazon-browser-fallback");
const browserWaitMs = Math.max(0, Number(parseArg("browser-wait-ms", "4000")) || 4000);
const EXTRACTOR_VERSION = amazonBrowserFallback
  ? "product_page_taxonomy_rules_v7_primary_category_item_tag_filter_amazon_browser_fallback"
  : robotsUrlFallback
  ? "product_page_taxonomy_rules_v7_primary_category_item_tag_filter_url_fallback"
  : "product_page_taxonomy_rules_v7_primary_category_item_tag_filter";

if (shardIndex >= shardCount) {
  throw new Error(`--shard-index must be less than --shard-count; got ${shardIndex}/${shardCount}`);
}

const robotsCache = new Map();
const lastDomainFetchAt = new Map();
let browserContextPromise = null;
let browserInstance = null;
let browserScreenshotsDir = null;

const CONTROLLED_ITEM_TAGS = [
  ["one-piece-swimsuit", "One-Piece Swimsuit", "swimwear", ["one piece swimsuit", "one-piece swimsuit", "one piece swim", "one-piece swim", "one piece", "one-piece", "swimsuit"]],
  ["bikini", "Bikini", "swimwear", ["bikini", "bikini top", "bikini bottom", "two piece swimsuit", "two-piece swimsuit"]],
  ["jeans", "Jeans", "bottoms", ["jeans", "jean", "denim jeans"]],
  ["pants", "Pants", "bottoms", ["pants", "pant", "trousers", "slacks", "sweatpant", "sweatpants", "wide leg", "straight leg", "ankle straight", "high rise ankle", "high rise", "mid rise", "bootcut", "flare"]],
  ["trousers", "Trousers", "bottoms", ["trousers", "trouser", "dress pants"]],
  ["leggings", "Leggings", "bottoms", ["leggings", "legging", "tights"]],
  ["shorts", "Shorts", "bottoms", ["shorts", "short", "bike short", "bike shorts", "supershort", "supershorts"]],
  ["skirt", "Skirt", "bottoms", ["skirt", "skirts", "skort", "skorts", "superskort", "superskorts"]],
  ["dress", "Dress", "dresses", ["dress", "dresses", "superdress", "sundress", "maxi dress", "midi dress", "mini dress"]],
  ["gown", "Gown", "dresses", ["gown", "evening gown", "formal dress"]],
  ["jumpsuit", "Jumpsuit", "jumpsuits", ["jumpsuit", "jumpsuits", "jump suit"]],
  ["romper", "Romper", "romper", ["romper", "rompers", "playsuit", "play suit"]],
  ["overalls", "Overalls", "dresses", ["overalls", "overall"]],
  ["bodysuit", "Bodysuit", "bodysuits", ["bodysuit", "bodysuits"]],
  ["top", "Top", "tops", ["top", "tops"]],
  ["blouse", "Blouse", "tops", ["blouse", "blouses"]],
  ["shirt", "Shirt", "tops", ["shirt", "shirts", "button down", "button-down", "button up", "button-up"]],
  ["tee", "Tee", "tops", ["tee", "t-shirt", "t shirt", "tshirt"]],
  ["tank", "Tank", "tops", ["tank", "tank top", "camisole", "cami"]],
  ["cami", "Cami", "tops", ["cami", "camisole", "camisoles"]],
  ["sweater", "Sweater", "tops", ["sweater", "sweaters", "sweatshirt", "sweatshirts", "cardigan", "pullover", "crewneck", "hoodie", "hoodies", "shrug", "shrugs", "shruggie"]],
  ["tunic", "Tunic", "tops", ["tunic", "tunics"]],
  ["vest", "Vest", "tops", ["vest", "vests"]],
  ["jacket", "Jacket", "outerwear", ["jacket", "jackets", "blazer", "shacket"]],
  ["coat", "Coat", "outerwear", ["coat", "coats", "parka", "trench"]],
  ["bra", "Bra", "intimates", ["bra", "bras", "bralette", "sports bra"]],
  ["bralette", "Bralette", "intimates", ["bralette", "bralettes"]],
  ["bustier", "Bustier", "intimates", ["bustier", "bustiers", "corset", "corsets"]],
  ["underwear", "Underwear", "intimates", ["underwear", "panty", "panties", "briefs", "thong"]],
  ["activewear", "Activewear", "activewear", ["activewear", "workout", "athletic", "performance wear"]],
  ["sports-bra", "Sports Bra", "activewear", ["sports bra", "sport bra"]],
  ["yoga-pants", "Yoga Pants", "activewear", ["yoga pants", "yoga pant", "yoga leggings"]],
  ["sneakers", "Sneakers", "shoes", ["sneakers", "sneaker", "trainers", "athletic shoes"]],
  ["boots", "Boots", "shoes", ["boots", "boot", "booties"]],
  ["heels", "Heels", "shoes", ["heels", "heel", "pumps"]],
  ["sandals", "Sandals", "shoes", ["sandals", "sandal"]],
  ["bag", "Bag", "accessories", ["bag", "bags", "handbag", "purse", "tote"]],
  ["belt", "Belt", "accessories", ["belt", "belts"]],
  ["scarf", "Scarf", "accessories", ["scarf", "scarves"]],
  ["sets", "Sets", "sets", ["matching set", "two piece set", "two-piece set", "pajama set", "pants set", "set"]],
  ["coverall", "Coverall", "jumpsuits", ["coverall", "coveralls"]],
];

const ATTRIBUTE_TAGS = [
  ["material", "denim", "Denim", ["denim", "jean fabric"]],
  ["material", "tweed", "Tweed", ["tweed"]],
  ["material", "faux_leather", "Faux Leather", ["faux leather", "vegan leather", "pleather"]],
  ["material", "leather", "Leather", ["leather"]],
  ["material", "linen", "Linen", ["linen"]],
  ["material", "cotton", "Cotton", ["cotton"]],
  ["material", "polyester", "Polyester", ["polyester"]],
  ["material", "rayon", "Rayon", ["rayon", "viscose"]],
  ["material", "wool", "Wool", ["wool", "merino"]],
  ["material", "cashmere", "Cashmere", ["cashmere"]],
  ["material", "corduroy", "Corduroy", ["corduroy"]],
  ["material", "suede", "Suede", ["suede", "faux suede"]],
  ["material", "ribbed", "Ribbed", ["ribbed", "rib knit", "rib-knit"]],
  ["material", "knit", "Knit", ["knit", "knitted"]],
  ["material", "lace", "Lace", ["lace"]],
  ["material", "satin", "Satin", ["satin"]],
  ["material", "silk", "Silk", ["silk"]],
  ["style", "cropped", "Cropped", ["cropped", "crop top"]],
  ["style", "oversized", "Oversized", ["oversized", "relaxed fit"]],
  ["style", "wide_leg", "Wide Leg", ["wide leg", "wide-leg"]],
  ["style", "straight_leg", "Straight Leg", ["straight leg", "straight-leg"]],
  ["style", "flare", "Flare", ["flare", "flared"]],
  ["style", "bootcut", "Bootcut", ["bootcut", "boot cut"]],
  ["style", "skinny", "Skinny", ["skinny"]],
  ["fit", "high_waisted", "High Waisted", ["high waisted", "high-waisted", "high rise", "high-rise"]],
  ["fit", "mid_rise", "Mid Rise", ["mid rise", "mid-rise"]],
  ["fit", "low_rise", "Low Rise", ["low rise", "low-rise"]],
  ["length", "mini", "Mini", ["mini dress", "mini skirt", "mini length"]],
  ["length", "midi", "Midi", ["midi dress", "midi skirt", "midi length"]],
  ["length", "maxi", "Maxi", ["maxi dress", "maxi skirt", "maxi length"]],
  ["detail", "pockets", "Pockets", ["pockets", "pocket"]],
  ["detail", "button_front", "Button Front", ["button front", "button-front"]],
  ["detail", "wrap", "Wrap", ["wrap dress", "wrap top", "wrap skirt"]],
  ["pattern", "striped", "Striped", ["striped", "stripe"]],
  ["pattern", "floral", "Floral", ["floral", "flower print"]],
  ["pattern", "plaid", "Plaid", ["plaid", "checkered", "checked"]],
  ["pattern", "animal_print", "Animal Print", ["animal print", "leopard", "zebra print", "snake print"]],
];

const MANUAL_TAXONOMY_OVERRIDES = new Map([
  [
    "https://bellybandit.com/products/bamboo-wrap",
    {
      primaryCategory: {
        mother_category_id: "accessories",
        category_confidence: "high",
        category_evidence: "Manual user review: Bamboo Wrap is a post-C-section abdominal recovery wrap/accessory.",
        category_source_field: "manual_user_review",
      },
      itemTags: [],
      attributeTags: [],
    },
  ],
  [
    "https://petalandpup.com/products/captivate-knit-cream",
    {
      primaryCategory: {
        mother_category_id: "tops",
        category_confidence: "high",
        category_evidence: "Manual user review: Captivate Knit Cream is a sweater; user noted tops and outerwear context.",
        category_source_field: "manual_user_review",
      },
      itemTags: [
        {
          clothing_type_id: "sweater",
          label: "Sweater",
          mother_category_id: "tops",
          confidence: "high",
          evidence: "Manual user review: Captivate Knit Cream is a sweater.",
          source_field: "manual_user_review",
          matched_phrase: "sweater",
        },
      ],
      attributeTags: [],
    },
  ],
]);

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function parseArgs(name) {
  const prefix = `--${name}=`;
  return process.argv
    .filter((arg) => arg.startsWith(prefix))
    .flatMap((arg) => arg.slice(prefix.length).split(","))
    .map((arg) => arg.trim())
    .filter(Boolean);
}

function timestampStem(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(".", "");
}


function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlTextArray(values) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  return `array[${items.map(sqlString).join(",")}]::text[]`;
}

function sqlJson(value) {
  return `${sqlString(JSON.stringify(value ?? null))}::jsonb`;
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

async function excludedProductPageIds() {
  const excluded = new Set();
  for (const reportPath of excludeApprovalReportPaths) {
    const resolved = path.resolve(reportPath);
    const report = JSON.parse(await readFile(resolved, "utf8"));
    if (report.review_dashboard_version !== "taxonomy_review_dashboard_v1") {
      throw new Error(`Exclude approval report is not a taxonomy review dashboard report: ${resolved}`);
    }
    for (const id of report.approved_product_page_ids || []) excluded.add(id);
    for (const decision of report.decisions || []) {
      if (decision.product_page_id) excluded.add(decision.product_page_id);
    }
  }
  for (const reportPath of excludeTaxonomyReportPaths) {
    const resolved = path.resolve(reportPath);
    const report = JSON.parse(await readFile(resolved, "utf8"));
    if (report.report_type !== "taxonomy" && !Array.isArray(report.results)) {
      throw new Error(`Exclude taxonomy report is not a taxonomy audit report: ${resolved}`);
    }
    for (const result of report.results || []) {
      if (result.product_page_id) excluded.add(result.product_page_id);
    }
  }
  return Array.from(excluded);
}

async function targetedProductPageIds() {
  if (!productPageIdsFile) return [];
  const raw = await readFile(path.resolve(productPageIdsFile), "utf8");
  return raw
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function candidateSql(excludedIds = [], targetedIds = []) {
  const excludedClause = excludedIds.length
    ? `and id::text not in (${excludedIds.map(sqlString).join(",")})`
    : "";
  const targetedClause = targetedIds.length
    ? `and id::text in (${targetedIds.map(sqlString).join(",")})`
    : "";
  const shardClause = shardCount > 1
    ? `and mod(abs(hashtext(normalized_product_page_url)), ${shardCount}) = ${shardIndex}`
    : "";
  return `
select coalesce(jsonb_agg(row_to_json(candidate) order by candidate.normalized_product_page_url), '[]'::jsonb)
from (
  select *
  from (
    select
      id::text,
      normalized_product_page_url,
      source_site,
      brand,
      product_title_raw,
      product_category_raw,
      mother_category_id,
      category_confidence,
      category_evidence,
      observed_clothing_type_ids,
      category_checked_at,
      row_number() over (
        partition by lower(split_part(regexp_replace(normalized_product_page_url, '^https?://', ''), '/', 1))
        order by category_checked_at nulls first, normalized_product_page_url
      ) as host_rank
    from staging.product_pages
    where normalized_product_page_url is not null
      and exists (
        select 1
        from public.images i
        where i.product_page_id = staging.product_pages.id
          and i.original_url_display is not null
      )
      ${onlyUnchecked ? "and category_checked_at is null" : ""}
      ${excludedClause}
      ${targetedClause}
      ${shardClause}
  ) ranked
  where host_rank <= ${maxPerDomain}
  order by category_checked_at nulls first, normalized_product_page_url
  limit ${limit}
) candidate;`;
}

function parseRobots(robotsText, targetUrl, userAgentValue) {
  const target = new URL(targetUrl);
  const agentNeedles = [userAgentValue.toLowerCase().split(/[ /;]/)[0], "*"].filter(Boolean);
  let applies = false;
  const rules = [];
  for (const rawLine of String(robotsText || "").split(/\r?\n/)) {
    const line = rawLine.replace(/#.*/, "").trim();
    if (!line) continue;
    const sep = line.indexOf(":");
    if (sep === -1) continue;
    const key = line.slice(0, sep).trim().toLowerCase();
    const value = line.slice(sep + 1).trim();
    if (key === "user-agent") {
      applies = agentNeedles.includes(value.toLowerCase());
      continue;
    }
    if (!applies || (key !== "allow" && key !== "disallow")) continue;
    if (!value) continue;
    const pathRule = value.replace(/\*.*$/, "");
    if (target.pathname.startsWith(pathRule)) rules.push({ type: key, rule: value, length: pathRule.length });
  }
  if (!rules.length) return { disallowed: false, rule: null };
  rules.sort((a, b) => b.length - a.length);
  const winner = rules[0];
  return { disallowed: winner.type === "disallow", rule: `${winner.type}: ${winner.rule}` };
}

async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal, redirect: "follow" });
  } finally {
    clearTimeout(timer);
  }
}

async function robotsDecision(url) {
  const parsed = new URL(url);
  const origin = parsed.origin;
  if (!robotsCache.has(origin)) {
    try {
      const response = await fetchWithTimeout(`${origin}/robots.txt`, { headers: { "User-Agent": userAgent } });
      const text = await response.text();
      robotsCache.set(origin, { ok: response.ok, text: response.ok ? text : "", error: response.ok ? null : `robots http ${response.status}` });
    } catch (error) {
      robotsCache.set(origin, { ok: false, text: "", error: error?.name === "AbortError" ? "robots timeout" : String(error?.message || error) });
    }
  }
  const robots = robotsCache.get(origin);
  if (!robots.ok) return { disallowed: false, rule: null, error: robots.error };
  return { ...parseRobots(robots.text, url, userAgent), error: null };
}

async function respectDomainDelay(url) {
  const host = new URL(url).hostname;
  const last = lastDomainFetchAt.get(host) || 0;
  const waitMs = Math.max(0, perDomainDelayMs - (Date.now() - last));
  if (waitMs) await sleep(waitMs);
  lastDomainFetchAt.set(host, Date.now());
}

function decodeHtml(value) {
  return String(value || "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

export function stripTags(value) {
  return decodeHtml(String(value || "").replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
}

function firstMatch(regex, text) {
  const match = String(text || "").match(regex);
  return match ? decodeHtml(match[1]).trim() : "";
}

function normalizeJsonLdType(value) {
  const values = Array.isArray(value) ? value : [value];
  return values.map((entry) => String(entry || "").toLowerCase());
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
  if (typeof value === "object") {
    collectImageValues(value.url || value.contentUrl || value.src, baseUrl, images);
  }
  return images;
}

function textPartsFromUnknown(value, parts = []) {
  if (value === null || value === undefined) return parts;
  if (typeof value === "string" || typeof value === "number") {
    parts.push(String(value));
    return parts;
  }
  if (Array.isArray(value)) {
    for (const item of value) textPartsFromUnknown(item, parts);
    return parts;
  }
  if (typeof value === "object") {
    for (const key of ["name", "title", "category", "description", "sku"]) {
      if (value[key] !== undefined) textPartsFromUnknown(value[key], parts);
    }
  }
  return parts;
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

function firstLikelyImageUrl(values, baseUrl) {
  return uniqueLikelyImageUrls(values, baseUrl)[0] || "";
}

function parseJsonLdBlocks(html, baseUrl = "") {
  const blocks = Array.from(String(html || "").matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi));
  const productCoreParts = [];
  const productDescriptionParts = [];
  const breadcrumbParts = [];
  const productImages = [];
  const parseErrors = [];

  for (const block of blocks) {
    const raw = decodeHtml(block[1]).trim();
    if (!raw) continue;
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      parseErrors.push(String(error?.message || error));
      continue;
    }

    const nodes = collectJsonLdNodes(parsed);
    for (const node of nodes) {
      const types = normalizeJsonLdType(node["@type"]);
      if (types.includes("product")) {
        textPartsFromUnknown(
          {
            name: node.name,
            title: node.title,
            category: node.category,
            sku: node.sku,
          },
          productCoreParts,
        );
        textPartsFromUnknown(node.description, productDescriptionParts);
        collectImageValues(node.image, baseUrl, productImages);
        collectImageValues(node.offers?.image, baseUrl, productImages);
      }

      if (types.includes("breadcrumblist")) {
        const items = Array.isArray(node.itemListElement) ? node.itemListElement : [];
        for (const item of items) {
          if (item?.name) breadcrumbParts.push(item.name);
          if (item?.item?.name) breadcrumbParts.push(item.item.name);
        }
      }
    }
  }

  return {
    product_core: stripTags(productCoreParts.join(" ")),
    product_description: stripTags(productDescriptionParts.join(" ")),
    breadcrumb: stripTags(breadcrumbParts.join(" > ")),
    product_images: productImages,
    parse_error_count: parseErrors.length,
  };
}

function metaContent(html, attributeName, attributeValue) {
  const escapedName = attributeName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const escapedValue = attributeValue.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regexes = [
    new RegExp(`<meta[^>]+${escapedName}=["']${escapedValue}["'][^>]+content=["']([^"']+)["'][^>]*>`, "i"),
    new RegExp(`<meta[^>]+content=["']([^"']+)["'][^>]+${escapedName}=["']${escapedValue}["'][^>]*>`, "i"),
  ];
  for (const regex of regexes) {
    const value = firstMatch(regex, html);
    if (value) return value;
  }
  return "";
}

function extractPageTextFields(html, url, candidate) {
  const jsonLd = parseJsonLdBlocks(html, url);
  const title = firstMatch(/<title[^>]*>([\s\S]*?)<\/title>/i, html)
    || metaContent(html, "property", "og:title")
    || candidate.product_title_raw
    || "";
  const description = metaContent(html, "name", "description")
    || metaContent(html, "property", "og:description")
    || "";
  const jsonLdImages = uniqueLikelyImageUrls(jsonLd.product_images, url);
  const metaImages = uniqueLikelyImageUrls([
    metaContent(html, "property", "og:image"),
    metaContent(html, "name", "twitter:image"),
  ], url);
  const catalogImageUrls = jsonLdImages.length ? jsonLdImages : metaImages;
  let urlSlug = "";
  try {
    const parsed = new URL(url);
    urlSlug = decodeURIComponent(parsed.pathname).replace(/[-_/]+/g, " ");
  } catch {
    urlSlug = url;
  }
  return {
    json_ld_product_core: jsonLd.product_core,
    json_ld_product_description: jsonLd.product_description,
    title: stripTags(title),
    breadcrumb: jsonLd.breadcrumb,
    description: stripTags(description),
    url_slug: stripTags(urlSlug),
    catalog_image_url: catalogImageUrls[0] || "",
    catalog_image_urls: catalogImageUrls,
    catalog_image_source: jsonLdImages.length ? "json_ld" : metaImages.length ? "meta" : "",
    catalog_image_fetch_status: catalogImageUrls.length ? "found" : html ? "not_found" : "not_fetched",
    workbook_fallback: stripTags([candidate.product_title_raw, candidate.product_category_raw, ...(candidate.observed_clothing_type_ids || [])].filter(Boolean).join(" ")),
    json_ld_parse_error_count: jsonLd.parse_error_count,
  };
}

function urlSlugFromUrl(url) {
  try {
    const parsed = new URL(url);
    return stripTags(decodeURIComponent(parsed.pathname).replace(/[-_/]+/g, " "));
  } catch {
    return stripTags(url);
  }
}

function extractUrlOnlyTextFields(url) {
  return extractPageTextFields("", url, {});
}

export function catalogFromFields(fields, { error = "" } = {}) {
  return {
    catalog_image_url: fields.catalog_image_url || "",
    catalog_image_urls: Array.isArray(fields.catalog_image_urls)
      ? fields.catalog_image_urls
      : fields.catalog_image_url
        ? [fields.catalog_image_url]
        : [],
    catalog_image_source: fields.catalog_image_source || "",
    catalog_image_fetch_status: fields.catalog_image_fetch_status || (error ? "error" : "not_found"),
    catalog_image_fetch_error: error,
  };
}

function isAmazonProductUrl(parsedUrl) {
  return /(^|\.)amazon\.com$/i.test(parsedUrl.hostname) && /\/dp\//i.test(parsedUrl.pathname);
}

function asinFromUrl(url) {
  const match = String(url || "").match(/\/dp\/([^/?#]+)/i);
  return (match?.[1] || "unknown").replace(/[^a-z0-9_-]/gi, "_");
}

export function normalizeBrowserBreadcrumb(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((part) => part.trim())
    .filter((part) => part && part !== "›")
    .join(" > ");
}

async function amazonBrowserContext() {
  if (!browserContextPromise) {
    browserContextPromise = (async () => {
      const { chromium } = await import("playwright");
      browserInstance = await chromium.launch({ headless: true });
      return browserInstance.newContext({
        viewport: { width: 1365, height: 1600 },
        userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        locale: "en-US",
      });
    })();
  }
  return browserContextPromise;
}

async function closeAmazonBrowserContext() {
  if (browserInstance) {
    await browserInstance.close();
    browserInstance = null;
    browserContextPromise = null;
  }
}

async function extractAmazonBrowserTextFields(url) {
  const context = await amazonBrowserContext();
  const page = await context.newPage();
  const asin = asinFromUrl(url);
  const screenshotPath = browserScreenshotsDir
    ? path.join(browserScreenshotsDir, `${asin}.png`)
    : null;
  try {
    const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    if (browserWaitMs) await page.waitForTimeout(browserWaitMs);
    const pageTitle = await page.title().catch(() => "");
    const breadcrumbRaw = await page
      .locator("#wayfinding-breadcrumbs_feature_div, .a-breadcrumb")
      .first()
      .innerText({ timeout: 2500 })
      .catch(() => "");
    const productSummary = await page
      .locator("#productOverview_feature_div, #feature-bullets, #productDescription")
      .first()
      .innerText({ timeout: 2500 })
      .catch(() => "");
    const catalogImagePayload = await page
      .locator("#landingImage, #imgTagWrapperId img, img[data-old-hires]")
      .first()
      .evaluate((img) => ({
        primary: img.getAttribute("data-old-hires") || img.getAttribute("src") || "",
        dynamicImages: Object.keys(JSON.parse(img.getAttribute("data-a-dynamic-image") || "{}")),
      }))
      .catch(() => "");
    const catalogImageUrls = uniqueLikelyImageUrls(
      [catalogImagePayload?.primary, ...(catalogImagePayload?.dynamicImages || [])],
      page.url(),
    );
    if (screenshotPath) await page.screenshot({ path: screenshotPath, fullPage: false });
    const fields = {
      json_ld_product_core: "",
      json_ld_product_description: "",
      title: stripTags(pageTitle),
      breadcrumb: stripTags(normalizeBrowserBreadcrumb(breadcrumbRaw)),
      description: stripTags(productSummary),
      url_slug: "",
      catalog_image_url: catalogImageUrls[0] || "",
      catalog_image_urls: catalogImageUrls,
      catalog_image_source: catalogImageUrls.length ? "amazon_browser" : "",
      catalog_image_fetch_status: catalogImageUrls.length ? "found" : "not_found",
      workbook_fallback: "",
      json_ld_parse_error_count: 0,
    };
    return {
      fields,
      screenshotPath,
      httpStatus: response?.status() ?? null,
      finalUrl: page.url(),
    };
  } finally {
    await page.close().catch(() => {});
  }
}

function findPhrase(fields, phrases) {
  const priority = ["title", "json_ld_product_core", "breadcrumb", "url_slug", "json_ld_product_description", "description", "workbook_fallback"];
  for (const sourceField of priority) {
    const text = String(fields[sourceField] || "");
    const lower = text.toLowerCase();
    for (const phrase of phrases) {
      const pattern = new RegExp(`(^|[^a-z0-9])${phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^a-z0-9]|$)`, "i");
      const match = lower.match(pattern);
      if (match) {
        const start = Math.max(0, match.index - 80);
        const evidence = text.slice(start, Math.min(text.length, match.index + phrase.length + 120)).trim();
        return { source_field: sourceField, evidence, phrase };
      }
    }
  }
  return null;
}

function confidenceForSource(sourceField) {
  if (sourceField === "title" || sourceField === "title_pattern" || sourceField === "json_ld_product_core" || sourceField === "breadcrumb") return "high";
  if (sourceField === "url_slug" || sourceField === "json_ld_product_description" || sourceField === "description") return "medium";
  return "low";
}

function confidenceRank(confidence) {
  return { high: 3, medium: 2, low: 1 }[confidence] || 0;
}

function sourceRank(sourceField) {
  return {
    title: 6,
    title_pattern: 6,
    json_ld_product_core: 5,
    breadcrumb: 4,
    url_slug: 3,
    json_ld_product_description: 2,
    description: 2,
    workbook_fallback: 1,
  }[sourceField] || 0;
}

function tagRank(tag) {
  return confidenceRank(tag.confidence) * 10 + sourceRank(tag.source_field) + categoryTieBreakBoost(tag);
}

function categoryTieBreakBoost(tag) {
  const phrase = String(tag.matched_phrase || "").toLowerCase();
  const evidence = String(tag.evidence || "").toLowerCase();
  if (tag.mother_category_id === "swimwear" && /\b(bikini|swim|swimsuit)\b/.test(`${phrase} ${evidence}`)) return 0.4;
  if (tag.mother_category_id === "dresses" && /\bdress\b/.test(`${phrase} ${evidence}`)) return 0.4;
  if (tag.mother_category_id === "jumpsuits" && /\b(jumpsuit|jump suit|coverall)\b/.test(`${phrase} ${evidence}`)) return 0.4;
  if (tag.mother_category_id === "sets" && /\bset\b/.test(`${phrase} ${evidence}`)) return 0.35;
  if (tag.mother_category_id === "outerwear" && /\b(jacket|coat|blazer|shacket|parka|trench)\b/.test(`${phrase} ${evidence}`)) return 0.35;
  if (tag.mother_category_id === "activewear" && /\bsports?\s+bras?\b/.test(`${phrase} ${evidence}`)) return 0.35;
  if (tag.mother_category_id === "tops" && /\b(blouse|tank top|tanks?|shirt|tee|t-shirt|top)\b/.test(`${phrase} ${evidence}`)) return 0.3;
  if (tag.mother_category_id === "bodysuits" && /\bbodysuits?\b/.test(`${phrase} ${evidence}`)) return 0.3;
  if (tag.mother_category_id === "intimates" && /\b(bustier|corset|bralette|underwear|panty|panties)\b/.test(`${phrase} ${evidence}`)) return 0.3;
  if (tag.mother_category_id === "bottoms" && /\b(wide leg|straight leg|bootcut|flare|short|skort|legging|pant)\b/.test(`${phrase} ${evidence}`)) return 0.25;
  return 0;
}

function sortedTags(tags) {
  return [...tags].sort((a, b) => tagRank(b) - tagRank(a) || a.clothing_type_id.localeCompare(b.clothing_type_id));
}

function sourceGroup(sourceField) {
  if (["title", "title_pattern", "json_ld_product_core", "breadcrumb", "url_slug"].includes(sourceField)) return "strong_page";
  if (["json_ld_product_description", "description"].includes(sourceField)) return "page_description";
  return "fallback";
}

function candidateItemTagsForWrites(itemTags) {
  const strong = itemTags.filter((tag) => sourceGroup(tag.source_field) === "strong_page");
  if (strong.length) return strong;
  const description = itemTags.filter((tag) => sourceGroup(tag.source_field) === "page_description");
  if (description.length) return description;
  return [];
}

export function extractTaxonomy(fields) {
  const itemTags = [];
  const attributeTags = [];

  for (const [id, label, motherCategoryId, phrases] of CONTROLLED_ITEM_TAGS) {
    const found = findPhrase(fields, phrases);
    if (!found) continue;
    itemTags.push({
      clothing_type_id: id,
      label,
      mother_category_id: motherCategoryId,
      confidence: confidenceForSource(found.source_field),
      evidence: found.evidence,
      source_field: found.source_field,
      matched_phrase: found.phrase,
    });
  }
  const titlePatternTag = titlePatternItemTag(fields.title);
  if (titlePatternTag && !itemTags.some((tag) => tag.clothing_type_id === titlePatternTag.clothing_type_id)) {
    itemTags.push(titlePatternTag);
  }

  for (const [tagType, tagId, label, phrases] of ATTRIBUTE_TAGS) {
    const found = findPhrase(fields, phrases);
    if (!found) continue;
    attributeTags.push({
      tag_type: tagType,
      tag_id: tagId,
      label,
      confidence: confidenceForSource(found.source_field),
      evidence: found.evidence,
      source_field: found.source_field,
      matched_phrase: found.phrase,
    });
  }

  const itemTagsSorted = sortedTags(candidateItemTagsForWrites(itemTags));
  const categoryVotes = new Map();
  for (const tag of itemTagsSorted) {
    const current = categoryVotes.get(tag.mother_category_id);
    const rank = tagRank(tag);
    if (!current || rank > current.rank) {
      categoryVotes.set(tag.mother_category_id, { rank, tag });
    }
  }
  const broadVotes = Array.from(categoryVotes.entries()).sort((a, b) => b[1].rank - a[1].rank);
  const broad = broadVotes[0];
  const runnerUp = broadVotes[1];
  const categoryAmbiguous = Boolean(broad && runnerUp && broad[1].rank === runnerUp[1].rank);
  const primaryCategory = broad && !categoryAmbiguous
    ? {
        mother_category_id: broad[0],
        category_confidence: broad[1].tag.confidence,
        category_evidence: broad[1].tag.evidence,
        category_source_field: broad[1].tag.source_field,
      }
    : null;
  const primaryRank = broad?.[1]?.rank ?? 0;
  const itemTagsForOutput = primaryCategory
    ? itemTagsSorted.filter((tag) =>
        tag.mother_category_id === primaryCategory.mother_category_id || tagRank(tag) >= primaryRank
      )
    : itemTagsSorted;

  return {
    primaryCategory,
    itemTags: itemTagsForOutput,
    attributeTags,
    categoryAmbiguous,
    categoryVotes: broadVotes.map(([motherCategoryId, vote]) => ({
      mother_category_id: motherCategoryId,
      rank: vote.rank,
      evidence_tag: vote.tag.clothing_type_id,
      source_field: vote.tag.source_field,
      confidence: vote.tag.confidence,
    })),
  };
}

function manualTaxonomyOverride(url) {
  const key = normalizeComparableProductUrl(url);
  const override = MANUAL_TAXONOMY_OVERRIDES.get(key);
  return override
    ? {
        ...override,
        categoryAmbiguous: false,
        categoryVotes: [{
          mother_category_id: override.primaryCategory.mother_category_id,
          rank: 99,
          evidence_tag: override.itemTags?.[0]?.clothing_type_id || "manual",
          source_field: "manual_user_review",
          confidence: override.primaryCategory.category_confidence,
        }],
      }
    : null;
}

function normalizeComparableProductUrl(value) {
  try {
    const url = new URL(String(value || ""));
    url.hash = "";
    url.search = "";
    url.hostname = url.hostname.replace(/^www\./i, "").toLowerCase();
    url.pathname = url.pathname.replace(/\/+$/, "");
    return url.href;
  } catch {
    return String(value || "").trim();
  }
}

function titlePatternItemTag(title) {
  const productTitle = String(title || "")
    .replace(/\s+\|\s+.*$/, "")
    .replace(/\s+by\s+.+$/i, "")
    .trim();
  if (!productTitle) return null;
  const patterns = [
    ["one-piece-swimsuit", "One-Piece Swimsuit", "swimwear", /\b(one[-\s]?piece swimsuit|one[-\s]?piece swim|swimsuit)\b/i],
    ["bikini", "Bikini", "swimwear", /\b(bikini|two[-\s]?piece swimsuit)\b/i],
    ["jeans", "Jeans", "bottoms", /\bjeans?\b/i],
    ["pants", "Pants", "bottoms", /\b(pants?|trousers?|slacks|sweatpants?|wide leg|straight leg|ankle straight|high rise ankle|high rise|mid rise|bootcut|flare)\b/i],
    ["leggings", "Leggings", "bottoms", /\b(leggings?|tights)\b/i],
    ["shorts", "Shorts", "bottoms", /\b(shorts?|bike shorts?|supershorts?)\b/i],
    ["skirt", "Skirt", "bottoms", /\b(skirts?|skorts?|superskorts?)\b/i],
    ["dress", "Dress", "dresses", /\b(dresses|dress|superdress|sundress)\b/i],
    ["gown", "Gown", "dresses", /\bgowns?\b/i],
    ["jumpsuit", "Jumpsuit", "jumpsuits", /\b(jumpsuits?|jump suits?)\b/i],
    ["romper", "Romper", "romper", /\b(rompers?|playsuits?|play suits?)\b/i],
    ["bodysuit", "Bodysuit", "bodysuits", /\bbodysuits?\b/i],
    ["top", "Top", "tops", /\btops?\b/i],
    ["blouse", "Blouse", "tops", /\bblouses?\b/i],
    ["shirt", "Shirt", "tops", /\b(shirts?|button[-\s]?ups?)\b/i],
    ["tee", "Tee", "tops", /\b(tees?|t[-\s]?shirts?)\b/i],
    ["tank", "Tank", "tops", /\b(tank tops?|tanks?|camisoles?|camis?)\b/i],
    ["sweater", "Sweater", "tops", /\b(sweaters?|sweatshirts?|cardigans?|pullovers?|crewnecks?|hoodies?|shrugs?|shruggies?)\b/i],
    ["coverall", "Coverall", "jumpsuits", /\bcoveralls?\b/i],
    ["sets", "Sets", "sets", /\b(pajama set|pants set|sets?)\b/i],
    ["jacket", "Jacket", "outerwear", /\b(jackets?|blazers?|shackets?)\b/i],
    ["coat", "Coat", "outerwear", /\b(coats?|parkas?|trenches|trench coats?)\b/i],
  ];
  for (const [clothingTypeId, label, motherCategoryId, pattern] of patterns) {
    const match = productTitle.match(pattern);
    if (!match) continue;
    return {
      clothing_type_id: clothingTypeId,
      label,
      mother_category_id: motherCategoryId,
      confidence: "high",
      evidence: productTitle,
      source_field: "title_pattern",
      matched_phrase: match[0].toLowerCase(),
    };
  }
  return null;
}

const urlBoilerplateTokens = new Set([
  "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with",
  "amazon", "apparel", "boutique", "buy", "catalog", "category", "clothing", "collection", "collections",
  "dp", "fashion", "gp", "item", "items", "men", "mens", "new", "page", "pages", "p", "product",
  "products", "sale", "shop", "sku", "store", "women", "womens",
]);

function meaningfulUrlTokens(urlSlug) {
  return String(urlSlug || "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => {
      if (token.length < 3) return false;
      if (/^[0-9]+$/.test(token)) return false;
      if (/^[a-z]?[0-9a-z]{8,}$/.test(token) && /\d/.test(token)) return false;
      return !urlBoilerplateTokens.has(token);
    });
}

function allProposedTaxonomyEntries(taxonomy) {
  return [
    ...(taxonomy?.primaryCategory ? [{
      type: "primary_category",
      source_field: taxonomy.primaryCategory.category_source_field,
      evidence: taxonomy.primaryCategory.category_evidence,
    }] : []),
    ...(taxonomy?.itemTags || []).map((tag) => ({ type: "item_tag", ...tag })),
    ...(taxonomy?.attributeTags || []).map((tag) => ({ type: "attribute_tag", ...tag })),
  ];
}

function validateUrlFallbackTaxonomy(fields, taxonomy) {
  const entries = allProposedTaxonomyEntries(taxonomy);
  const reasons = [];
  if (!entries.length) {
    return { passed: true, reasons: ["no_proposed_taxonomy_updates"] };
  }

  const nonUrlSources = entries
    .filter((entry) => entry.source_field !== "url_slug")
    .map((entry) => `${entry.type}:${entry.source_field || "missing"}`);
  if (nonUrlSources.length) {
    reasons.push(`non_url_slug_evidence:${nonUrlSources.slice(0, 5).join(",")}`);
  }

  const itemTags = taxonomy?.itemTags || [];
  if (!taxonomy?.primaryCategory) reasons.push("missing_primary_category");
  if (!itemTags.length) reasons.push("missing_item_tag");

  const tokens = meaningfulUrlTokens(fields.url_slug);
  if (tokens.length < 2) reasons.push("weak_url_slug_token_count");

  const urlSlugLower = String(fields.url_slug || "").toLowerCase();
  const itemPhraseMatches = itemTags.filter((tag) => {
    const phrase = String(tag.matched_phrase || "").toLowerCase().trim();
    return tag.source_field === "url_slug" && phrase && urlSlugLower.includes(phrase);
  });
  if (!itemPhraseMatches.length) reasons.push("no_item_phrase_in_url_slug");

  return {
    passed: reasons.length === 0,
    reasons: reasons.length ? reasons : ["url_slug_has_item_phrase_and_context"],
    meaningful_url_tokens: tokens.slice(0, 12),
    proposed_entry_count: entries.length,
    item_phrase_matches: itemPhraseMatches.map((tag) => tag.matched_phrase).slice(0, 5),
  };
}

function emptyTaxonomy() {
  return {
    primaryCategory: null,
    itemTags: [],
    attributeTags: [],
    categoryAmbiguous: false,
    categoryVotes: [],
  };
}

async function auditOne(candidate) {
  const base = {
    product_page_id: candidate.id,
    normalized_product_page_url: candidate.normalized_product_page_url,
    workbook_hints: {
      product_title_raw: candidate.product_title_raw,
      product_category_raw: candidate.product_category_raw,
      observed_clothing_type_ids: candidate.observed_clothing_type_ids || [],
      current_mother_category_id: candidate.mother_category_id,
      current_category_confidence: candidate.category_confidence,
      current_category_evidence: candidate.category_evidence,
    },
  };
  let parsed;
  try {
    parsed = new URL(candidate.normalized_product_page_url);
  } catch {
    return { ...base, skipped: true, skip_reason: "invalid_url" };
  }

  const robots = await robotsDecision(parsed.href);
  if (robots.disallowed) {
    if (amazonBrowserFallback && isAmazonProductUrl(parsed)) {
      try {
        const browserResult = await extractAmazonBrowserTextFields(parsed.href);
        const taxonomy = manualTaxonomyOverride(candidate.normalized_product_page_url) || extractTaxonomy(browserResult.fields);
        const workbookDisagreement = Boolean(
          taxonomy.primaryCategory?.mother_category_id &&
            candidate.mother_category_id &&
            taxonomy.primaryCategory.mother_category_id !== candidate.mother_category_id,
        );
        return {
          ...base,
          skipped: false,
          skip_reason: "amazon_browser_fallback",
          robots_disallowed: true,
          robots_rule: robots.rule,
          robots_error: robots.error,
          http_status: browserResult.httpStatus,
          final_url: browserResult.finalUrl,
          browser_screenshot_path: browserResult.screenshotPath,
          extracted_fields_preview: Object.fromEntries(Object.entries(browserResult.fields).map(([key, value]) => [key, String(value || "").slice(0, 500)])),
          catalog: catalogFromFields(browserResult.fields),
          proposed: taxonomy,
          workbook_disagreement: workbookDisagreement,
        };
      } catch (error) {
        if (!robotsUrlFallback) {
          return {
            ...base,
            skipped: true,
            skip_reason: "amazon_browser_fallback_error",
            robots_disallowed: true,
            robots_rule: robots.rule,
            robots_error: robots.error,
            error: String(error?.message || error),
          };
        }
      }
    }
    if (robotsUrlFallback) {
      const fields = extractUrlOnlyTextFields(parsed.href);
      const manualOverride = manualTaxonomyOverride(candidate.normalized_product_page_url);
      const rawTaxonomy = manualOverride || extractTaxonomy(fields);
      const urlFallbackGuard = manualOverride
        ? { passed: true, reasons: ["manual_user_review_override"], proposed_entry_count: allProposedTaxonomyEntries(rawTaxonomy).length }
        : validateUrlFallbackTaxonomy(fields, rawTaxonomy);
      const taxonomy = urlFallbackGuard.passed ? rawTaxonomy : emptyTaxonomy();
      const workbookDisagreement = Boolean(
        taxonomy.primaryCategory?.mother_category_id &&
          candidate.mother_category_id &&
          taxonomy.primaryCategory.mother_category_id !== candidate.mother_category_id,
      );
      return {
        ...base,
        skipped: false,
        skip_reason: "robots_url_fallback",
        robots_disallowed: true,
        robots_rule: robots.rule,
        robots_error: robots.error,
        http_status: null,
        final_url: parsed.href,
        extracted_fields_preview: Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, String(value || "").slice(0, 500)])),
        catalog: catalogFromFields(fields),
        proposed: taxonomy,
        url_fallback_guard: urlFallbackGuard,
        blocked_url_fallback_proposed: urlFallbackGuard.passed ? null : rawTaxonomy,
        workbook_disagreement: workbookDisagreement,
      };
    }
    return { ...base, skipped: true, skip_reason: "robots_disallowed", robots_rule: robots.rule, robots_error: robots.error };
  }

  await respectDomainDelay(parsed.href);
  try {
    const response = await fetchWithTimeout(parsed.href, {
      headers: {
        "User-Agent": userAgent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      },
    });
    let finalParsed = null;
    try {
      finalParsed = new URL(response.url || parsed.href);
    } catch {
      finalParsed = null;
    }
    const redirectedToHomepage = Boolean(
      finalParsed &&
        finalParsed.origin !== "null" &&
        finalParsed.origin === parsed.origin &&
        finalParsed.pathname.replace(/\/+$/, "") === "" &&
        parsed.pathname.replace(/\/+$/, "") !== "",
    );
    if (response.status >= 400) {
      return {
        ...base,
        skipped: true,
        skip_reason: `http_status_${response.status}`,
        skip_description: `Fetched URL returned HTTP ${response.status}; likely unavailable or not a usable product page.`,
        http_status: response.status,
        final_url: response.url || parsed.href,
      };
    }
    if (redirectedToHomepage) {
      return {
        ...base,
        skipped: true,
        skip_reason: "redirected_to_homepage",
        skip_description: "Product URL redirected to the site homepage instead of a product page.",
        http_status: response.status,
        final_url: response.url || parsed.href,
      };
    }
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("text/html")) {
      return {
        ...base,
        skipped: true,
        skip_reason: `non_html:${contentType || "unknown"}`,
        skip_description: `Fetched URL returned non-HTML content type: ${contentType || "unknown"}.`,
        http_status: response.status,
        final_url: response.url || parsed.href,
      };
    }
    const html = await response.text();
    const fields = extractPageTextFields(html, response.url || parsed.href, candidate);
    const candidateSlug = urlSlugFromUrl(candidate.normalized_product_page_url);
    if (!meaningfulUrlTokens(fields.url_slug).length && candidateSlug) {
      fields.url_slug = candidateSlug;
    }
    const taxonomy = manualTaxonomyOverride(candidate.normalized_product_page_url) || extractTaxonomy(fields);
    const workbookDisagreement = Boolean(
      taxonomy.primaryCategory?.mother_category_id &&
        candidate.mother_category_id &&
        taxonomy.primaryCategory.mother_category_id !== candidate.mother_category_id,
    );
    return {
      ...base,
      skipped: false,
      http_status: response.status,
      final_url: response.url || parsed.href,
      extracted_fields_preview: Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, String(value || "").slice(0, 500)])),
      catalog: catalogFromFields(fields),
      proposed: taxonomy,
      workbook_disagreement: workbookDisagreement,
    };
  } catch (error) {
    return { ...base, skipped: true, skip_reason: error?.name === "AbortError" ? "timeout" : "fetch_error", error: String(error?.message || error) };
  }
}

function updateSql(results) {
  const statements = [];
  for (const result of results) {
    if (result.skipped || !result.proposed) continue;
    const category = result.proposed.primaryCategory;
    const catalog = result.catalog || {};
    if (category) {
      statements.push(`
update staging.product_pages
set
  mother_category_id = ${sqlString(category.mother_category_id)},
  category_confidence = ${sqlString(category.category_confidence)},
  category_evidence = ${sqlString(category.category_evidence)},
  category_source_field = ${sqlString(category.category_source_field)},
  category_extractor_version = ${sqlString(EXTRACTOR_VERSION)},
  category_checked_at = now(),
  catalog_image_url = coalesce(nullif(${sqlString(catalog.catalog_image_url)}, ''), catalog_image_url),
  catalog_image_urls = case
    when cardinality(${sqlTextArray(catalog.catalog_image_urls)}) > 0 then ${sqlTextArray(catalog.catalog_image_urls)}
    else catalog_image_urls
  end,
  catalog_image_source = coalesce(nullif(${sqlString(catalog.catalog_image_source)}, ''), catalog_image_source),
  catalog_image_fetched_at = now(),
  catalog_image_fetch_status = ${sqlString(catalog.catalog_image_fetch_status || "not_found")},
  catalog_image_fetch_error = nullif(${sqlString(catalog.catalog_image_fetch_error || "")}, ''),
  raw_metadata = raw_metadata || jsonb_build_object('taxonomy_extracted_at', now(), 'taxonomy_final_url', ${sqlString(result.final_url)})
where id = ${sqlString(result.product_page_id)}::uuid;`);
    } else {
      statements.push(`
update staging.product_pages
set
  category_extractor_version = ${sqlString(EXTRACTOR_VERSION)},
  category_checked_at = now(),
  catalog_image_url = coalesce(nullif(${sqlString(catalog.catalog_image_url)}, ''), catalog_image_url),
  catalog_image_urls = case
    when cardinality(${sqlTextArray(catalog.catalog_image_urls)}) > 0 then ${sqlTextArray(catalog.catalog_image_urls)}
    else catalog_image_urls
  end,
  catalog_image_source = coalesce(nullif(${sqlString(catalog.catalog_image_source)}, ''), catalog_image_source),
  catalog_image_fetched_at = now(),
  catalog_image_fetch_status = ${sqlString(catalog.catalog_image_fetch_status || "not_found")},
  catalog_image_fetch_error = nullif(${sqlString(catalog.catalog_image_fetch_error || "")}, '')
where id = ${sqlString(result.product_page_id)}::uuid;`);
    }
    for (const tag of result.proposed.itemTags || []) {
      statements.push(`
insert into staging.product_page_clothing_type_tags (product_page_id, clothing_type_id, evidence)
values (${sqlString(result.product_page_id)}::uuid, ${sqlString(tag.clothing_type_id)}, ${sqlString(tag.evidence)})
on conflict (product_page_id, clothing_type_id) do update set
  evidence = excluded.evidence;`);
    }
    for (const tag of result.proposed.attributeTags || []) {
      statements.push(`
insert into staging.product_page_attribute_tags
  (product_page_id, tag_type, tag_id, label, confidence, evidence, source_field, extractor_version)
values
  (${sqlString(result.product_page_id)}::uuid, ${sqlString(tag.tag_type)}, ${sqlString(tag.tag_id)}, ${sqlString(tag.label)}, ${sqlString(tag.confidence)}, ${sqlString(tag.evidence)}, ${sqlString(tag.source_field)}, ${sqlString(EXTRACTOR_VERSION)})
on conflict (product_page_id, tag_type, tag_id) do update set
  label = excluded.label,
  confidence = excluded.confidence,
  evidence = excluded.evidence,
  source_field = excluded.source_field,
  extractor_version = excluded.extractor_version,
  updated_at = now();`);
    }
  }
  return `begin;\n${statements.join("\n")}\ncommit;`;
}

function summarize(results) {
  const summary = {
    skipped: 0,
    ambiguous_primary_categories: 0,
    proposed_primary_categories: {},
    proposed_item_tag_count: 0,
    proposed_attribute_tag_count: 0,
    workbook_disagreements: 0,
  };
  for (const result of results) {
    if (result.skipped) {
      summary.skipped += 1;
      continue;
    }
    const category = result.proposed?.primaryCategory?.mother_category_id || "none";
    summary.proposed_primary_categories[category] = (summary.proposed_primary_categories[category] || 0) + 1;
    if (result.proposed?.categoryAmbiguous) summary.ambiguous_primary_categories += 1;
    summary.proposed_item_tag_count += result.proposed?.itemTags?.length || 0;
    summary.proposed_attribute_tag_count += result.proposed?.attributeTags?.length || 0;
    if (result.workbook_disagreement) summary.workbook_disagreements += 1;
  }
  return summary;
}

async function requirePassedVerificationReport(expectedType) {
  if (!verifiedReportPath) {
    throw new Error(`Apply mode requires --verified-report=/absolute/path/dev_refresh_report_verify_${expectedType}_*.json from a passed report verification.`);
  }
  const report = JSON.parse(await readFile(path.resolve(verifiedReportPath), "utf8"));
  if (report.report_type !== expectedType || report.passed !== true) {
    throw new Error(`Verification report did not pass for ${expectedType}: ${verifiedReportPath}`);
  }
  return report;
}

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function pill(label, value) {
  if (!value) return "";
  return `<span class="pill"><strong>${htmlEscape(label)}:</strong> ${htmlEscape(value)}</span>`;
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function taxonomyHumanReviewRows(results) {
  return (results || [])
    .filter((result) =>
      result.skipped ||
      result.proposed?.categoryAmbiguous ||
      (!result.proposed?.primaryCategory && (result.proposed?.itemTags || []).length > 0) ||
      result.workbook_disagreement,
    )
    .map((result) => {
      const primary = result.proposed?.primaryCategory || null;
      return {
        product_page_id: result.product_page_id,
        normalized_product_page_url: result.normalized_product_page_url,
        review_reason: result.skipped
          ? result.skip_reason || "audit_skipped"
          : result.proposed?.categoryAmbiguous
            ? "ambiguous_category"
            : result.workbook_disagreement
              ? "workbook_disagreement"
              : "tags_without_primary_category",
        workbook_category: result.workbook_hints?.current_mother_category_id || "",
        workbook_type_hints: (result.workbook_hints?.observed_clothing_type_ids || []).join("|"),
        proposed_category: primary?.mother_category_id || "",
        proposed_category_confidence: primary?.category_confidence || "",
        proposed_category_source: primary?.category_source_field || "",
        proposed_item_tags: (result.proposed?.itemTags || []).map((tag) => tag.clothing_type_id).join("|"),
        proposed_attribute_tags: (result.proposed?.attributeTags || []).map((tag) => `${tag.tag_type}:${tag.tag_id}`).join("|"),
        category_votes_json: JSON.stringify(result.proposed?.categoryVotes || []),
        evidence: primary?.category_evidence || result.skip_reason || "",
        final_url: result.final_url || "",
      };
    });
}

function buildTaxonomyHumanReviewCsv(rows) {
  const headers = [
    "product_page_id",
    "normalized_product_page_url",
    "review_reason",
    "workbook_category",
    "workbook_type_hints",
    "proposed_category",
    "proposed_category_confidence",
    "proposed_category_source",
    "proposed_item_tags",
    "proposed_attribute_tags",
    "category_votes_json",
    "evidence",
    "final_url",
  ];
  return [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n") + "\n";
}

function buildReviewHtml(report) {
  const rows = report.results
    .map((result) => {
      const primary = result.proposed?.primaryCategory;
      const itemTags = result.proposed?.itemTags || [];
      const attributeTags = result.proposed?.attributeTags || [];
      return `
        <article class="card ${result.workbook_disagreement ? "disagreement" : ""}">
          <h2><a href="${htmlEscape(result.normalized_product_page_url)}" target="_blank" rel="noreferrer">${htmlEscape(result.normalized_product_page_url)}</a></h2>
          <div class="section">
            ${pill("skipped", result.skipped ? result.skip_reason || "yes" : "")}
            ${pill("workbook category", result.workbook_hints?.current_mother_category_id)}
            ${pill("workbook type hints", (result.workbook_hints?.observed_clothing_type_ids || []).join(", "))}
            ${pill("proposed category", primary ? `${primary.mother_category_id} (${primary.category_confidence})` : "none")}
            ${pill("source", primary?.category_source_field)}
            ${pill("browser screenshot", result.browser_screenshot_path)}
            ${pill("ambiguous category", result.proposed?.categoryAmbiguous ? "yes" : "")}
            ${pill("workbook disagreement", result.workbook_disagreement ? "yes" : "")}
          </div>
          <div class="columns">
            <section>
              <h3>Item Tags</h3>
              <ul>${itemTags.map((tag) => `<li>${htmlEscape(tag.clothing_type_id)} <small>${htmlEscape(tag.confidence)} · ${htmlEscape(tag.source_field)}</small><br><q>${htmlEscape(tag.evidence)}</q></li>`).join("") || "<li>none</li>"}</ul>
            </section>
            <section>
              <h3>Attribute Tags</h3>
              <ul>${attributeTags.map((tag) => `<li>${htmlEscape(tag.tag_type)}:${htmlEscape(tag.tag_id)} <small>${htmlEscape(tag.confidence)} · ${htmlEscape(tag.source_field)}</small><br><q>${htmlEscape(tag.evidence)}</q></li>`).join("") || "<li>none</li>"}</ul>
            </section>
          </div>
          <details>
            <summary>Field preview</summary>
            <pre>${htmlEscape(JSON.stringify(result.extracted_fields_preview || {}, null, 2))}</pre>
          </details>
          <details>
            <summary>Category votes</summary>
            <pre>${htmlEscape(JSON.stringify(result.proposed?.categoryVotes || [], null, 2))}</pre>
          </details>
        </article>`;
    })
    .join("\n");
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FWM Dev Product Page Taxonomy Audit</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; color: #1f2933; }
    header { margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(440px, 1fr)); gap: 16px; }
    .card { border: 1px solid #d9e2ec; border-radius: 8px; padding: 14px; background: #fff; }
    .card.disagreement { border-color: #d64545; }
    h2 { font-size: 14px; overflow-wrap: anywhere; }
    h3 { font-size: 13px; margin-bottom: 6px; }
    .section { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 12px; }
    .pill { background: #f0f4f8; border-radius: 999px; padding: 4px 8px; font-size: 12px; }
    .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    ul { padding-left: 18px; }
    li { margin-bottom: 8px; font-size: 13px; }
    small { color: #627d98; }
    q { color: #334e68; }
    pre { white-space: pre-wrap; font-size: 11px; background: #f8fafc; padding: 8px; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <header>
    <h1>FWM Dev Product Page Taxonomy Audit</h1>
    <p>Generated ${htmlEscape(report.generated_at)}. Mode: ${htmlEscape(report.mode)}. Candidates: ${htmlEscape(report.candidate_count)}. Workbook disagreements: ${htmlEscape(report.summary.workbook_disagreements)}.</p>
  </header>
  <main class="grid">${rows}</main>
</body>
</html>
`;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Product-page taxonomy audit guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);
  if (apply) {
    throw new Error("Direct taxonomy audit apply is disabled. Run a dry-run audit, verify it, then use npm run dev-images:taxonomy:promote with the exact report.");
  }

  const excludedIds = await excludedProductPageIds();
  const targetedIds = await targetedProductPageIds();
  const candidates = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, candidateSql(excludedIds, targetedIds)));
  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  const reportStem = `dev_product_page_taxonomy_audit_${timestampStem(new Date(generatedAt))}`;
  browserScreenshotsDir = path.join(reportsDir, `${reportStem}_screenshots`);
  if (amazonBrowserFallback) await mkdir(browserScreenshotsDir, { recursive: true });
  const results = [];
  try {
    for (const candidate of candidates) results.push(await auditOne(candidate));
  } finally {
    await closeAmazonBrowserContext();
  }

  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `${reportStem}.json`);
  const reviewHtmlPath = path.join(reportsDir, `${reportStem}.html`);
  const humanReviewCsvPath = path.join(reportsDir, `${reportStem}_human_review.csv`);
  const summary = summarize(results);
  const humanReviewRows = taxonomyHumanReviewRows(results);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    extractor_version: EXTRACTOR_VERSION,
    user_agent: userAgent,
    limit,
    only_unchecked: onlyUnchecked,
    include_all_product_pages: includeAllProductPages,
    timeout_ms: timeoutMs,
    browser_wait_ms: amazonBrowserFallback ? browserWaitMs : null,
    browser_screenshots_dir: amazonBrowserFallback ? browserScreenshotsDir : null,
    per_domain_delay_ms: perDomainDelayMs,
    max_per_domain: maxPerDomain,
    exclude_approval_report_paths: excludeApprovalReportPaths.map((reportPath) => path.resolve(reportPath)),
    exclude_taxonomy_report_paths: excludeTaxonomyReportPaths.map((reportPath) => path.resolve(reportPath)),
    excluded_product_page_count: excludedIds.length,
    shard_count: shardCount,
    shard_index: shardIndex,
    candidate_count: candidates.length,
    summary,
    review_html_path: reviewHtmlPath,
    human_review_csv_path: humanReviewCsvPath,
    human_review_count: humanReviewRows.length,
    results,
  };

  if (apply) {
    requireExplicitWriteFlag();
    await requirePassedVerificationReport("taxonomy");
    if (results.length) runPsql(process.env.DEV_DATABASE_URL, updateSql(results));
  }

  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(reviewHtmlPath, buildReviewHtml(report), "utf8");
  await writeFile(humanReviewCsvPath, buildTaxonomyHumanReviewCsv(humanReviewRows), "utf8");
  console.log(`Wrote product-page taxonomy audit report: ${reportPath}`);
  console.log(`Wrote product-page taxonomy review HTML: ${reviewHtmlPath}`);
  console.log(`Wrote product-page taxonomy human-review CSV: ${humanReviewCsvPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Candidates audited: ${report.candidate_count}`);
  console.log(`Human-review rows: ${humanReviewRows.length}`);
  console.log(`Summary: ${JSON.stringify(summary)}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

// Only run the full audit when invoked directly as a CLI. Importing this module
// (e.g. to reuse extractTaxonomy in the free Amazon backfill) must NOT trigger a run.
const invokedDirectly = process.argv[1]
  && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  main().catch((error) => {
    console.error(error.message || error);
    process.exitCode = 1;
  });
}
