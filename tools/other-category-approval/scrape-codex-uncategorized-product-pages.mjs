#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const inputPath = path.join(toolDir, "codex-uncategorized-product-pages.txt");
const outputPath = path.join(toolDir, "codex-uncategorized-product-pages.result.ndjson");

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const lastFetchByHost = new Map();

function decodeHtml(value) {
  return String(value || "")
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(parseInt(n, 10)))
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ");
}

function stripTags(value) {
  return decodeHtml(String(value || "").replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function parseRows(text) {
  const rows = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const match = lines[i].match(/^\[(\d+)\]\s+product_page_id=([0-9a-f-]+)(.*)$/i);
    if (!match) continue;
    const url = (lines[i + 1] || "").trim();
    const sig = match[3] || "";
    rows.push({
      index: Number(match[1]),
      product_page_id: match[2],
      url,
      seed_brand: (sig.match(/\bbrand=([^|]+)/) || [])[1]?.trim() || "",
      seed_title: (sig.match(/\btitle=([^|]+)/) || [])[1]?.trim() || "",
    });
  }
  return rows;
}

function metaContent(html, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`<meta[^>]+(?:property|name)=["']${escaped}["'][^>]+content=["']([^"']*)["'][^>]*>`, "i");
  return decodeHtml((html.match(re) || [])[1] || "");
}

function parseJsonState(html) {
  const match = html.match(/window\.__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\})\s*<\/script>/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]);
  } catch {
    return null;
  }
}

function extractTitle(html, url, seedTitle) {
  if (seedTitle) return seedTitle;
  const host = new URL(url).hostname;
  if (host.includes("shopcider")) {
    const state = parseJsonState(html);
    const productName = state?.storeState?.productionDetail?.productionDetail?.productName;
    if (productName) return stripTags(productName);
  }
  const h1 = (html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i) || [])[1];
  if (h1) return stripTags(h1);
  const og = metaContent(html, "og:title");
  if (og) return stripTags(og);
  const title = (html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1];
  return stripTags(title)
    .replace(/\s*[:|-]\s*(L\.L\.Bean|Cider).*$/i, "")
    .trim();
}

function extractBrand(html, url, seedBrand) {
  if (seedBrand) return seedBrand === "llbean" ? "L.L.Bean" : seedBrand;
  const site = metaContent(html, "og:site_name");
  if (site) return site;
  const host = new URL(url).hostname;
  if (host.includes("llbean")) return "L.L.Bean";
  if (host.includes("shopcider")) return "Cider";
  return "";
}

function extractLlbeanBreadcrumb(html) {
  const block = (html.match(/<ol[^>]+id=["']breadcrumb-list["'][^>]*>([\s\S]*?)<\/ol>/i) || [])[1] || "";
  const parts = [...block.matchAll(/<span[^>]+itemProp=["']name["'][^>]*>([\s\S]*?)<\/span>/gi)]
    .map((m) => stripTags(m[1]))
    .filter((p) => p && !/^L\.L\.Bean$/i.test(p));
  return parts.join(" > ");
}

function extractCiderSignals(html) {
  const state = parseJsonState(html);
  const detail = state?.storeState?.productionDetail?.productionDetail || {};
  const attrs = [];
  for (const row of detail.productDetailList || []) {
    for (const value of row?.content || []) attrs.push(String(value));
  }
  return {
    description: metaContent(html, "description") || detail.productDesc || "",
    attrs: attrs.join(" ; "),
  };
}

function extractBreadcrumb(html, url, title) {
  const host = new URL(url).hostname;
  if (host.includes("llbean")) return extractLlbeanBreadcrumb(html);
  if (host.includes("shopcider")) {
    const signals = extractCiderSignals(html);
    const text = `${title} ${signals.description} ${signals.attrs}`;
    if (/\bmini dresses?\b/i.test(text)) return "Clothing > Dresses > Mini Dresses";
    if (/\bdresses?\b/i.test(text)) return "Clothing > Dresses";
    return "Clothing";
  }
  return "";
}

const TYPE_PATTERNS = [
  ["jumpsuits", /\b(overalls?|shortalls?|rompers?|playsuits?|catsuits?|boilersuits?|flight suits?)\b/i],
  ["swimsuit", /\b(swimsuits?|bikinis?|tankinis?|tanksuits?|rash guards?|swim dresses?|swim skirts?|swim shorts?|swimwear)\b/i],
  ["dress", /\b(dresses?|shirtdresses?|sundresses?|sun dresses?|gowns?)\b/i],
  ["skirt", /\b(skirts?|skorts?)\b/i],
  ["jeans", /\bjeans?\b/i],
  ["pants", /\b(pants?|trousers?|chinos?|corduroys?|capris?|culottes?)\b/i],
  ["shorts", /\bshorts?\b(?!-sleeve)/i],
  ["leggings", /\b(leggings?|tights?)\b/i],
  ["joggers", /\bjoggers?\b/i],
  ["coat", /\b(coats?|parkas?|jackets?|blazers?|vests?|anoraks?|raincoats?)\b/i],
  ["sweatshirt", /\b(sweatshirts?|hoodies?|sweaters?|pullovers?|fleece)\b/i],
  ["shirt", /\b(shirts?|blouses?|tees?|t-shirts?|shells?|scoopnecks?|crew tops?|base layers?|tanks?|camisoles?|camis?|tops?|tunics?|henleys?|turtlenecks?)\b/i],
  ["bra", /\b(bras?|bralettes?)\b/i],
  ["underwear", /\b(underwear|briefs?|panties|slips?|sleepwear|pajamas?|nightgowns?|robes?)\b/i],
  ["set", /\b(sets?|matching set|twin set)\b/i],
  ["accessory", /\b(hats?|scarves?|gloves?|mittens?|belts?|bags?|totes?|socks?)\b/i],
  ["footwear", /\b(shoes?|boots?|sandals?|sneakers?|slippers?|flip-flops?|clogs?|moccasins?)\b/i],
  ["non-apparel", /\b(gift cards?|yoga mats?|shipping|protection|warranty)\b/i],
];

function observedItemType(text) {
  for (const [type, re] of TYPE_PATTERNS) {
    if (re.test(text)) return type;
  }
  return "";
}

function classify(title, breadcrumb, description) {
  const text = `${title} ${breadcrumb} ${description}`.toLowerCase();
  if (/\bpage not available\b/.test(text)) {
    return { category: "", notClothing: true, type: "unavailable_product_page", confidence: "low" };
  }
  const type = observedItemType(text);
  if (type === "footwear" || type === "non-apparel") {
    return { category: "", notClothing: true, type, confidence: "high" };
  }
  if (["overalls", "shortalls", "rompers", "jumpsuits"].includes(type)) {
    return { category: "jumpsuits", notClothing: false, type, confidence: "high" };
  }
  if (type === "swimsuit") return { category: "swimwear", notClothing: false, type, confidence: "high" };
  if (type === "dress") return { category: "dresses", notClothing: false, type, confidence: "high" };
  if (["skirt", "jeans", "pants", "shorts", "leggings", "joggers"].includes(type)) {
    return { category: "bottoms", notClothing: false, type, confidence: "high" };
  }
  if (["sweatshirt", "shirt"].includes(type)) return { category: "tops", notClothing: false, type, confidence: "high" };
  if (type === "coat") return { category: "outerwear", notClothing: false, type, confidence: "high" };
  if (["bra", "underwear"].includes(type)) return { category: "intimates", notClothing: false, type, confidence: "high" };
  if (type === "set") return { category: "sets", notClothing: false, type, confidence: "medium" };
  if (type === "accessory") return { category: "accessories", notClothing: false, type, confidence: "medium" };
  if (/\b(active|workout|training|running|yoga)\b/.test(text)) {
    return { category: "activewear", notClothing: false, type: type || "activewear", confidence: "medium" };
  }
  return { category: "", notClothing: false, type, confidence: "low" };
}

async function fetchHtml(url) {
  const host = new URL(url).hostname;
  const last = lastFetchByHost.get(host) || 0;
  const waitMs = Math.max(0, 1100 - (Date.now() - last));
  if (waitMs) await sleep(waitMs);
  lastFetchByHost.set(host, Date.now());

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(url, {
      redirect: "follow",
      signal: controller.signal,
      headers: {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      },
    });
    return { status: response.status, finalUrl: response.url || url, html: await response.text() };
  } finally {
    clearTimeout(timer);
  }
}

function evidenceFor(title, breadcrumb, description, cls) {
  if (cls.type === "unavailable_product_page") {
    return "LLBean returned Page Not Available; no product schema, title, or breadcrumb was present to categorize";
  }
  const bits = [];
  if (title) bits.push(`title says ${title}`);
  if (breadcrumb) bits.push(`breadcrumb ${breadcrumb}`);
  if (!breadcrumb && description) bits.push(`description mentions ${stripTags(description).slice(0, 90)}`);
  if (cls.notClothing) bits.push(`flagged as ${cls.type}`);
  return bits.join("; ").slice(0, 260);
}

async function main() {
  const rows = parseRows(await readFile(inputPath, "utf8"));
  const out = [];
  for (const row of rows) {
    try {
      const { status, finalUrl, html } = await fetchHtml(row.url);
      const title = extractTitle(html, finalUrl, row.seed_title);
      const brand = extractBrand(html, finalUrl, row.seed_brand);
      const breadcrumb = extractBreadcrumb(html, finalUrl, title);
      const ciderSignals = new URL(finalUrl).hostname.includes("shopcider") ? extractCiderSignals(html) : { description: metaContent(html, "description") };
      const description = `${ciderSignals.description || ""} ${ciderSignals.attrs || ""}`;
      const cls = classify(title, breadcrumb, description);
      out.push({
        product_page_id: row.product_page_id,
        url: row.url,
        product_title: title,
        brand,
        breadcrumb,
        observed_item_type: cls.type || observedItemType(`${title} ${breadcrumb} ${description}`),
        suggested_mother_category: cls.notClothing ? "" : cls.category,
        is_new_category: false,
        not_clothing: cls.notClothing,
        confidence: cls.category || cls.notClothing ? cls.confidence : "low",
        evidence: evidenceFor(title, breadcrumb, description, cls) || `HTTP ${status} ${finalUrl}`,
      });
      console.log(`[${row.index}/${rows.length}] ok ${status} ${title || "(no title)"}`);
    } catch (error) {
      out.push({
        product_page_id: row.product_page_id,
        url: row.url,
        product_title: row.seed_title || "",
        brand: row.seed_brand || "",
        breadcrumb: "",
        observed_item_type: "",
        suggested_mother_category: "",
        is_new_category: false,
        not_clothing: false,
        confidence: "low",
        evidence: `fetch failed: ${error?.message || error}`,
      });
      console.log(`[${row.index}/${rows.length}] failed ${row.url}: ${error?.message || error}`);
    }
  }

  await writeFile(outputPath, out.map((row) => JSON.stringify(row)).join("\n") + "\n");
  const unresolved = out.filter((row) => !row.not_clothing && !row.suggested_mother_category).length;
  console.log(`wrote ${outputPath}`);
  console.log(`rows=${out.length} unresolved=${unresolved} not_clothing=${out.filter((row) => row.not_clothing).length}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
