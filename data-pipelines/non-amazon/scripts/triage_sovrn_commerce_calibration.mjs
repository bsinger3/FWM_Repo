#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(__filename), "../../..");

const DEFAULT_TRACKER = path.join(
  repoRoot,
  "data-pipelines/non-amazon/docs/sovrn_commerce_apparel_triage_tracker.csv",
);
const DEFAULT_CALIBRATION = path.join(
  repoRoot,
  "data-pipelines/non-amazon/docs/sovrn_commerce_calibration_batch.csv",
);
const DEFAULT_OUTPUT = path.join(
  repoRoot,
  "data-pipelines/non-amazon/docs/sovrn_commerce_calibration_results.csv",
);

const CATEGORY_TERMS = [
  "women",
  "womens",
  "women's",
  "clothing",
  "dresses",
  "tops",
  "shirts",
  "pants",
  "jeans",
  "swim",
  "lingerie",
  "activewear",
];

const OUT_OF_SCOPE_TERMS = [
  "shoe",
  "shoes",
  "boot",
  "boots",
  "footwear",
  "sneaker",
  "sneakers",
  "sandals",
  "jewelry",
  "handbag",
  "bags",
  "accessories",
];

const PRODUCT_URL_PATTERNS = [
  /\/products?\//i,
  /\/product\//i,
  /\/p\//i,
  /\/prd\//i,
  /\/shop\/product/i,
  /productid=/i,
  /pid=/i,
  /skuId=/i,
];

const REVIEW_PROVIDERS = [
  ["Bazaarvoice", [/bazaarvoice/i, /bvseo/i, /bv_reviews/i, /api\.bazaarvoice\.com/i]],
  ["PowerReviews", [/powerreviews/i, /pr-review/i, /ui\.powerreviews\.com/i]],
  ["Yotpo", [/yotpo/i, /staticw2\.yotpo\.com/i]],
  ["Okendo", [/okendo/i, /okeReviews/i, /oke-widget/i]],
  ["Judge.me", [/judge\.me/i, /jdgm-/i, /judgeme_product_reviews/i]],
  ["Loox", [/loox/i, /looxReviews/i, /loox-rating/i]],
  ["Stamped", [/stamped\.io/i, /stamped-main-widget/i]],
  ["Reviews.io", [/reviews\.io/i, /widget\.reviews\.co\.uk/i, /ruk_rating_snippet/i]],
  ["TurnTo", [/turnto\.com/i, /TurnToCmd/i]],
  ["Shopify Product Reviews", [/shopify-product-reviews/i, /spr-container/i]],
];

const SIZE_PATTERNS = [
  /\bsize(?:s)?\b/i,
  /\bsize guide\b/i,
  /\bsize chart\b/i,
  /\bselect size\b/i,
  /\bfit\b/i,
  /\bmodel (?:is|wears|wearing)\b/i,
  /\bXS\b|\bS\b|\bM\b|\bL\b|\bXL\b/i,
];

const REVIEW_PATTERNS = [
  /\breviews?\b/i,
  /\bstar rating\b/i,
  /\bcustomer ratings?\b/i,
  /\bwrite a review\b/i,
];

const PHOTO_REVIEW_PATTERNS = [
  /review[^"'<>]{0,100}(?:image|photo|media)/i,
  /(?:image|photo|media)[^"'<>]{0,100}review/i,
  /customer photos/i,
  /reviews with photos/i,
  /bv-content-media/i,
  /pr-media/i,
  /yotpo-review-media/i,
  /oke-reviewContent-media/i,
  /jdgm-rev__pic/i,
  /loox-photo/i,
];

const BLOCK_PATTERNS = [
  /captcha/i,
  /access denied/i,
  /temporarily unavailable/i,
  /unusual traffic/i,
  /perimeterx/i,
  /px-captcha/i,
  /cloudflare challenge/i,
  /checking your browser/i,
  /just a moment/i,
  /cf-chl-/i,
  /akamai bot/i,
  /datadome/i,
  /bot detection/i,
  /security challenge/i,
];

const COUNTRY_PATTERNS = [
  ["US", /\bUnited States\b|\bU\.S\.\b|\bUSA\b|\bUS\b/],
  ["CA", /\bCanada\b/],
  ["GB", /\bUnited Kingdom\b|\bUK\b|\bGreat Britain\b/],
  ["AU", /\bAustralia\b/],
  ["NZ", /\bNew Zealand\b/],
  ["IE", /\bIreland\b/],
  ["DE", /\bGermany\b|\bDeutschland\b/],
  ["FR", /\bFrance\b/],
  ["ES", /\bSpain\b/],
  ["IT", /\bItaly\b/],
  ["NL", /\bNetherlands\b/],
  ["BE", /\bBelgium\b/],
  ["SE", /\bSweden\b/],
  ["NO", /\bNorway\b/],
  ["DK", /\bDenmark\b/],
  ["AE", /\bUnited Arab Emirates\b|\bUAE\b/],
];

function parseArgs() {
  const args = new Map();
  const raw = process.argv.slice(2);
  for (let i = 0; i < raw.length; i += 1) {
    const key = raw[i];
    if (!key.startsWith("--")) continue;
    const next = raw[i + 1];
    if (!next || next.startsWith("--")) {
      args.set(key, "true");
    } else {
      args.set(key, next);
      i += 1;
    }
  }
  return {
    tracker: args.get("--tracker") || DEFAULT_TRACKER,
    calibration: args.get("--calibration") || DEFAULT_CALIBRATION,
    output: args.get("--output") || DEFAULT_OUTPUT,
    limit: args.has("--limit") ? Number(args.get("--limit")) : Infinity,
    headed: args.get("--headed") === "true",
  };
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];
    if (inQuotes && ch === '"' && next === '"') {
      cell += '"';
      i += 1;
    } else if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (!inQuotes && ch === ",") {
      row.push(cell);
      cell = "";
    } else if (!inQuotes && (ch === "\n" || ch === "\r")) {
      if (ch === "\r" && next === "\n") i += 1;
      row.push(cell);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  const headers = rows.shift() || [];
  return {
    headers,
    records: rows.map((values) =>
      Object.fromEntries(headers.map((header, index) => [header, values[index] || ""])),
    ),
  };
}

function csvEscape(value) {
  const text = value == null ? "" : String(value).replace(/\s*\r?\n\s*/g, " ");
  if (/[",\r\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function writeCsv(filePath, headers, records) {
  const lines = [
    headers.map(csvEscape).join(","),
    ...records.map((record) => headers.map((header) => csvEscape(record[header] || "")).join(",")),
  ];
  fs.writeFileSync(filePath, `${lines.join("\n")}\n`, "utf8");
}

function absoluteUrl(url) {
  if (/^https?:\/\//i.test(url)) return url;
  return `https://${url}`;
}

function hostnameFromUrl(url) {
  try {
    return new URL(absoluteUrl(url)).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

function splitDomains(primaryDomains) {
  return primaryDomains
    .split(";")
    .map((domain) => domain.trim())
    .filter(Boolean);
}

function choosePrimaryUrl(record) {
  const domains = splitDomains(record.primary_domains || "");
  const merchant = (record.merchant_group || "").toLowerCase();
  const badHostPrefixes = ["images.", "image.", "jobs.", "apply.", "stores.", "link.", "tumblr.", "hello.", "e.", "t.em."];
  const badHostParts = ["career", "associatekiosk", "credit.", "assistive.", "corporate."];
  const marketHints = ["www2.hm.com", "jcrew.com", "bananarepublic.gap.com"];

  for (const hint of marketHints) {
    const hit = domains.find((domain) => hostnameFromUrl(domain) === hint);
    if (hit) return absoluteUrl(hit);
  }

  if (merchant.includes("j. crew")) {
    const hit = domains.find((domain) => hostnameFromUrl(domain) === "jcrew.com");
    if (hit) return absoluteUrl(hit);
  }

  const clean = domains.filter((domain) => {
    const host = hostnameFromUrl(domain);
    return (
      host &&
      !badHostPrefixes.some((prefix) => host.startsWith(prefix)) &&
      !badHostParts.some((part) => host.includes(part))
    );
  });

  const exactDotCom = clean.find((domain) => {
    const host = hostnameFromUrl(domain);
    return host.endsWith(".com") && host.split(".").length === 2;
  });
  if (exactDotCom) return absoluteUrl(exactDotCom);

  return absoluteUrl(clean[0] || domains[0] || "");
}

function inferCountryCodesFromDomains(primaryDomains) {
  const codes = new Set();
  for (const rawDomain of splitDomains(primaryDomains)) {
    const host = hostnameFromUrl(rawDomain);
    if (!host) continue;
    if (host.endsWith(".ca") || host.includes("gapcanada") || host.startsWith("ca.")) codes.add("CA");
    if (host.endsWith(".co.uk") || host.endsWith(".uk")) codes.add("GB");
    if (host.endsWith(".com.au") || host.startsWith("au.")) codes.add("AU");
    if (host.endsWith(".de") || host.startsWith("de.")) codes.add("DE");
    if (host.endsWith(".fr")) codes.add("FR");
    if (host.endsWith(".eu")) codes.add("EU");
    if (host.endsWith(".ae") || host.startsWith("ae.")) codes.add("AE");
    if (host.endsWith(".com") || host.endsWith(".us")) codes.add("US");
  }
  return [...codes].sort();
}

function primaryMarketFromUrl(url) {
  const host = hostnameFromUrl(url);
  if (host.endsWith(".ca") || host.startsWith("ca.") || host.includes("gapcanada")) return "CA";
  if (host.endsWith(".co.uk") || host.endsWith(".uk")) return "GB";
  if (host.endsWith(".com.au") || host.startsWith("au.")) return "AU";
  if (host.endsWith(".de") || host.startsWith("de.")) return "DE";
  if (host.endsWith(".fr")) return "FR";
  if (host.endsWith(".ae") || host.startsWith("ae.")) return "AE";
  if (host.endsWith(".com") || host.endsWith(".us")) return "US";
  return "";
}

function uniq(values) {
  return [...new Set(values.filter(Boolean))];
}

function scoreCategoryLink(link) {
  const text = `${link.text || ""} ${link.href || ""}`.toLowerCase();
  if (OUT_OF_SCOPE_TERMS.some((term) => text.includes(term))) return -100;
  let score = 0;
  for (const term of CATEGORY_TERMS) {
    if (text.includes(term)) score += term.includes("women") ? 4 : 2;
  }
  if (/\/women|womens|women-s|women_/.test(text)) score += 5;
  if (/\/sale|\/clearance|\/outlet/.test(text)) score -= 2;
  return score;
}

function isLikelyProductLink(link) {
  const text = `${link.text || ""} ${link.href || ""}`.toLowerCase();
  if (OUT_OF_SCOPE_TERMS.some((term) => text.includes(term))) return false;
  return PRODUCT_URL_PATTERNS.some((pattern) => pattern.test(link.href || ""));
}

function detectProvider(html) {
  const providers = REVIEW_PROVIDERS
    .filter(([, patterns]) => patterns.some((pattern) => pattern.test(html)))
    .map(([name]) => name);
  return uniq(providers).join("; ");
}

function detectStatus(html, responseStatus) {
  if (responseStatus && responseStatus >= 400) return `http_${responseStatus}`;
  if (BLOCK_PATTERNS.some((pattern) => pattern.test(html))) return "possible_block_or_challenge";
  return "fetched";
}

function detectCountries(text) {
  const codes = [];
  for (const [code, pattern] of COUNTRY_PATTERNS) {
    if (pattern.test(text)) codes.push(code);
  }
  return uniq(codes).sort();
}

async function safeGoto(page, url, waitUntil = "domcontentloaded") {
  try {
    const response = await page.goto(url, { waitUntil, timeout: 30000 });
    await page.waitForTimeout(2000);
    return {
      ok: true,
      status: response?.status() || "",
      url: page.url(),
      html: await page.content(),
      title: await page.title().catch(() => ""),
    };
  } catch (error) {
    return {
      ok: false,
      status: "",
      url,
      html: "",
      title: "",
      error: `${error.name || "Error"}: ${error.message || error}`,
    };
  }
}

async function settleDynamicPage(page) {
  for (let i = 0; i < 3; i += 1) {
    await page.mouse.wheel(0, 900).catch(() => {});
    await page.waitForTimeout(900);
  }
  await page.evaluate(() => window.scrollTo(0, 0)).catch(() => {});
  await page.waitForTimeout(500);
}

async function extractLinks(page) {
  return page
    .$$eval("a[href]", (anchors) =>
      anchors.map((anchor) => ({
        text: (anchor.textContent || "").replace(/\s+/g, " ").trim().slice(0, 160),
        href: anchor.href,
      })),
    )
    .catch(() => []);
}

async function visibleText(page) {
  return page
    .locator("body")
    .innerText({ timeout: 5000 })
    .catch(() => "");
}

async function inspectMerchant(context, record) {
  const page = await context.newPage();
  const primaryUrl = choosePrimaryUrl(record);
  const startedAt = new Date().toISOString();
  const result = {
    ...record,
    checked_at: startedAt,
    category_evidence_url: "",
    sample_pdp_urls: "",
    size_importance: "unknown",
    size_basis: "",
    reviews_present: "unknown",
    photo_reviews: "unknown",
    review_provider: "",
    review_photo_evidence: "",
    ships_to_country_codes: "",
    shipping_geo_status: "unknown",
    shipping_geo_evidence_url: "",
    shipping_geo_evidence_basis: "",
    primary_market_country: primaryMarketFromUrl(primaryUrl),
    product_url_geo_inheritance: "unknown",
    scrape_feasibility: "unknown",
    anti_bot_or_login_notes: "",
  };

  const home = await safeGoto(page, primaryUrl);
  if (!home.ok) {
    result.scrape_feasibility = "blocked_or_unreachable";
    result.anti_bot_or_login_notes = home.error;
    await page.close();
    return result;
  }

  const homeStatus = detectStatus(home.html, home.status);
  if (homeStatus !== "fetched") {
    result.scrape_feasibility = "blocked_or_needs_manual_review";
    result.anti_bot_or_login_notes = `${homeStatus} at ${home.url}`;
  }

  const homeLinks = await extractLinks(page);
  const categoryLink = homeLinks
    .map((link) => ({ ...link, score: scoreCategoryLink(link) }))
    .filter((link) => link.score > 0)
    .sort((a, b) => b.score - a.score)[0];

  if (categoryLink?.href) result.category_evidence_url = categoryLink.href;

  const shippingLink = homeLinks.find((link) => {
    const text = `${link.text || ""} ${link.href || ""}`.toLowerCase();
    return /(shipping|delivery|international|returns)/.test(text) && !/order-status|tracking/.test(text);
  });

  const domainCountries = inferCountryCodesFromDomains(record.primary_domains || "");
  let shippingCountries = domainCountries;
  let shippingBasis = domainCountries.length ? "storefront_locale" : "";
  let shippingEvidenceUrl = primaryUrl;

  if (shippingLink?.href) {
    const shippingPage = await safeGoto(page, shippingLink.href);
    if (shippingPage.ok) {
      const text = await visibleText(page);
      const policyCountries = detectCountries(text);
      if (policyCountries.length) {
        shippingCountries = uniq([...shippingCountries, ...policyCountries]).sort();
        shippingBasis = "shipping_policy";
        shippingEvidenceUrl = shippingPage.url;
      }
    }
  }

  result.ships_to_country_codes = shippingCountries.join("|");
  result.shipping_geo_evidence_url = shippingEvidenceUrl;
  result.shipping_geo_evidence_basis = shippingBasis || "manual_note";
  if (shippingCountries.length > 1) result.shipping_geo_status = "known_country_list";
  else if (shippingCountries.length === 1) result.shipping_geo_status = "market_specific_url";

  if (categoryLink?.href) {
    const category = await safeGoto(page, categoryLink.href);
    if (category.ok && detectStatus(category.html, category.status) === "fetched") {
      await settleDynamicPage(page);
      const categoryLinks = await extractLinks(page);
      const productLinks = uniq(categoryLinks.filter(isLikelyProductLink).map((link) => link.href)).slice(0, 5);
      result.sample_pdp_urls = productLinks.slice(0, 3).join(" | ");

      const htmlChunks = [home.html, category.html];
      for (const productUrl of productLinks.slice(0, 3)) {
        const pdp = await safeGoto(page, productUrl);
        if (!pdp.ok) continue;
        htmlChunks.push(pdp.html);
      }
      const combinedHtml = htmlChunks.join("\n");
      const provider = detectProvider(combinedHtml);
      result.review_provider = provider || "unknown";
      result.size_importance = SIZE_PATTERNS.some((pattern) => pattern.test(combinedHtml)) ? "yes" : "unknown";
      result.size_basis = result.size_importance === "yes" ? "sampled PDP/category pages expose size or fit language" : "";
      result.reviews_present = REVIEW_PATTERNS.some((pattern) => pattern.test(combinedHtml)) || provider ? "yes" : "unknown";
      result.photo_reviews = PHOTO_REVIEW_PATTERNS.some((pattern) => pattern.test(combinedHtml))
        ? "yes"
        : result.reviews_present === "yes"
          ? "unknown_sample_too_small"
          : "unknown";
      result.review_photo_evidence = result.photo_reviews === "yes" ? result.sample_pdp_urls || result.category_evidence_url : "";
    }
  } else {
    const provider = detectProvider(home.html);
    result.review_provider = provider || "unknown";
    result.size_importance = SIZE_PATTERNS.some((pattern) => pattern.test(home.html)) ? "yes" : "unknown";
    result.size_basis = result.size_importance === "yes" ? "homepage exposes size or fit language" : "";
    result.reviews_present = REVIEW_PATTERNS.some((pattern) => pattern.test(home.html)) || provider ? "yes" : "unknown";
  }

  if (!result.scrape_feasibility || result.scrape_feasibility === "unknown") {
    if (!result.category_evidence_url) result.scrape_feasibility = "needs_manual_category_confirmation";
    else if (result.reviews_present === "yes") result.scrape_feasibility = "triage_candidate";
    else result.scrape_feasibility = "category_confirmed_review_unknown";
  }

  result.product_url_geo_inheritance =
    result.shipping_geo_status === "known_country_list" || result.shipping_geo_status === "market_specific_url"
      ? "merchant_level_ok"
      : "unknown";

  await page.close();
  return result;
}

function mergeRows(trackerRecords, completedRows) {
  const byKey = new Map();
  for (const row of completedRows) byKey.set(`${row.merchant_group_id}::${row.merchant_group}`, row);
  return trackerRecords.map((row) => {
    const key = `${row.merchant_group_id}::${row.merchant_group}`;
    return byKey.has(key) ? { ...row, ...byKey.get(key) } : row;
  });
}

async function main() {
  const options = parseArgs();
  const calibrationText = fs.readFileSync(options.calibration, "utf8");
  const trackerText = fs.readFileSync(options.tracker, "utf8");
  const calibration = parseCsv(calibrationText);
  const tracker = parseCsv(trackerText);
  const rows = calibration.records
    .filter((row) => row.calibration_batch_order)
    .sort((a, b) => Number(a.calibration_batch_order) - Number(b.calibration_batch_order))
    .slice(0, options.limit);

  const browser = await chromium.launch({
    headless: !options.headed,
  });
  const context = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    viewport: { width: 1440, height: 1100 },
  });

  const completed = [];
  for (const row of rows) {
    console.log(`triage ${row.calibration_batch_order}. ${row.merchant_group}`);
    const inspected = await inspectMerchant(context, row);
    completed.push(inspected);
    console.log(
      `  ${inspected.scrape_feasibility}; category=${inspected.category_evidence_url || "unknown"}; reviews=${inspected.reviews_present}/${inspected.photo_reviews}; shipping=${inspected.ships_to_country_codes || "unknown"}`,
    );
  }

  await context.close();
  await browser.close();

  writeCsv(options.output, calibration.headers, completed);
  const merged = mergeRows(tracker.records, completed);
  const mergedCalibration = mergeRows(calibration.records, completed);
  writeCsv(options.tracker, tracker.headers, merged);
  writeCsv(options.calibration, calibration.headers, mergedCalibration);
  console.log(`wrote ${options.output}`);
  console.log(`updated ${options.tracker}`);
  console.log(`updated ${options.calibration}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
