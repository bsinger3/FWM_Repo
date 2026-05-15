#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const DEFAULT_BATCH_SIZE = 25;
const DEFAULT_MAX_PAGES = 3;
const DEFAULT_DOMAIN = "www.amazon.com";
const DEFAULT_OUTPUT_PREFIX = "batch_";
const ASIN_COLUMNS = new Set(["asin", "ASIN", "asin_value", "ASIN_Value", "asin_values", "ASIN_Values"]);
const TERMINAL_BLOCK_PATTERNS = [
  /enter the characters you see below/i,
  /sorry, we just need to make sure you're not a robot/i,
  /captcha/i,
  /id="ap_login_form"/i,
  /\/ax\/claim\?/i,
  /sign in with your password/i,
];

function repoRoot() {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

function dataRoot() {
  return path.resolve(repoRoot(), "..", "FWM_Data");
}

function defaultOutputDir() {
  return path.join(dataRoot(), "raw", "direct_amazon");
}

function parseArgs(argv) {
  const args = {
    batchSize: DEFAULT_BATCH_SIZE,
    maxPages: DEFAULT_MAX_PAGES,
    outputDir: defaultOutputDir(),
    startBatchNumber: null,
    sleepMs: 4000,
    pageTimeoutMs: 45000,
    limit: null,
    headed: false,
    keepBrowserOpen: false,
    domain: DEFAULT_DOMAIN,
    asins: [],
    debugDir: null,
  };

  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => {
      index += 1;
      if (index >= argv.length) {
        throw new Error(`Missing value for ${arg}`);
      }
      return argv[index];
    };

    if (arg === "--batch-size") args.batchSize = Number(next());
    else if (arg === "--max-pages") args.maxPages = Number(next());
    else if (arg === "--output-dir") args.outputDir = path.resolve(next());
    else if (arg === "--start-batch-number") args.startBatchNumber = Number(next());
    else if (arg === "--sleep-ms") args.sleepMs = Number(next());
    else if (arg === "--page-timeout-ms") args.pageTimeoutMs = Number(next());
    else if (arg === "--limit") args.limit = Number(next());
    else if (arg === "--domain") args.domain = next();
    else if (arg === "--asin") args.asins.push(next().trim().toUpperCase());
    else if (arg === "--debug-dir") args.debugDir = path.resolve(next());
    else if (arg === "--headed") args.headed = true;
    else if (arg === "--keep-browser-open") args.keepBrowserOpen = true;
    else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else if (arg.startsWith("--")) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positional.push(arg);
    }
  }

  if (positional.length > 1 || (positional.length === 0 && args.asins.length === 0)) {
    throw new Error("Expected one input CSV path or at least one --asin value.");
  }
  args.csvPath = positional[0] ? resolveInputPath(positional[0]) : null;

  if (!Number.isInteger(args.batchSize) || args.batchSize < 1) {
    throw new Error("--batch-size must be a positive integer.");
  }
  if (!Number.isInteger(args.maxPages) || args.maxPages < 1) {
    throw new Error("--max-pages must be a positive integer.");
  }
  if (args.limit !== null && (!Number.isInteger(args.limit) || args.limit < 1)) {
    throw new Error("--limit must be a positive integer.");
  }
  if (args.startBatchNumber !== null && (!Number.isInteger(args.startBatchNumber) || args.startBatchNumber < 1)) {
    throw new Error("--start-batch-number must be a positive integer.");
  }
  if (!Number.isFinite(args.sleepMs) || args.sleepMs < 0) {
    throw new Error("--sleep-ms must be zero or greater.");
  }

  return args;
}

function printHelp() {
  console.log(`Usage: node scripts/scrape_amazon_reviews_direct.mjs <asins.csv> [options]

Scrapes public Amazon media review pages directly with Playwright.

Options:
  --batch-size <n>            ASINs per output batch. Default: ${DEFAULT_BATCH_SIZE}
  --max-pages <n>             Review pages per ASIN. Default: ${DEFAULT_MAX_PAGES}
  --output-dir <path>         Output directory. Default: ../FWM_Data/raw/direct_amazon
  --start-batch-number <n>    First batch file number. Default: next available
  --sleep-ms <n>              Delay after each page request. Default: 4000
  --page-timeout-ms <n>       Navigation timeout. Default: 45000
  --limit <n>                 Only scrape the first n ASINs, useful for smoke tests
  --headed                    Show Chromium while scraping
  --keep-browser-open         Leave headed browser open at the end
  --domain <host>             Amazon host. Default: www.amazon.com
  --asin <asin>               Scrape one ASIN directly. Can be repeated
  --debug-dir <path>          Save HTML snapshots for blocked/no-review pages
`);
}

function resolveInputPath(inputPath) {
  if (path.isAbsolute(inputPath)) return inputPath;
  return path.resolve(repoRoot(), inputPath);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (inQuotes) {
      if (char === '"' && next === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') inQuotes = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }

  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }

  return rows.filter((csvRow) => csvRow.some((value) => value.trim()));
}

function loadAsins(csvPath, limit) {
  if (!fs.existsSync(csvPath)) {
    throw new Error(`CSV file not found: ${csvPath}`);
  }

  const rows = parseCsv(fs.readFileSync(csvPath, "utf8").replace(/^\uFEFF/, ""));
  if (rows.length < 2) {
    throw new Error("Input CSV must contain a header row and at least one data row.");
  }

  const headers = rows[0].map((value) => value.trim());
  const asinIndex = headers.findIndex((header) => ASIN_COLUMNS.has(header));
  if (asinIndex === -1) {
    throw new Error(`Input CSV must include one ASIN column: ${Array.from(ASIN_COLUMNS).join(", ")}`);
  }

  const seen = new Set();
  const asins = [];
  for (const row of rows.slice(1)) {
    const asin = (row[asinIndex] || "").trim().toUpperCase();
    if (!asin || seen.has(asin)) continue;
    seen.add(asin);
    asins.push(asin);
    if (limit !== null && asins.length >= limit) break;
  }

  if (asins.length === 0) {
    throw new Error("No ASINs found in the input CSV.");
  }
  return asins;
}

function normalizeAsins(values, limit) {
  const seen = new Set();
  const asins = [];
  for (const value of values) {
    const asin = value.trim().toUpperCase();
    if (!asin || seen.has(asin)) continue;
    seen.add(asin);
    asins.push(asin);
    if (limit !== null && asins.length >= limit) break;
  }
  if (asins.length === 0) {
    throw new Error("No ASINs found.");
  }
  return asins;
}

function chunked(values, size) {
  const batches = [];
  for (let index = 0; index < values.length; index += size) {
    batches.push(values.slice(index, index + size));
  }
  return batches;
}

function nextBatchNumber(destination) {
  if (!fs.existsSync(destination)) return 1;
  const numbers = fs.readdirSync(destination)
    .map((name) => name.match(/^batch_(\d+)\.json$/)?.[1])
    .filter(Boolean)
    .map(Number);
  return numbers.length ? Math.max(...numbers) + 1 : 1;
}

function batchPath(destination, batchNumber) {
  return path.join(destination, `${DEFAULT_OUTPUT_PREFIX}${String(batchNumber).padStart(3, "0")}.json`);
}

function metadataPath(destination, batchNumber) {
  return path.join(destination, "_runs", `${DEFAULT_OUTPUT_PREFIX}${String(batchNumber).padStart(3, "0")}.run.json`);
}

function writeJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function reviewPageUrl(domain, asin, pageNumber) {
  const url = new URL(`https://${domain}/product-reviews/${asin}/`);
  url.searchParams.set("ie", "UTF8");
  url.searchParams.set("reviewerType", "all_reviews");
  url.searchParams.set("mediaType", "media_reviews_only");
  url.searchParams.set("pageNumber", String(pageNumber));
  return url.toString();
}

function normalizeImageUrl(url) {
  if (!url) return "";
  return url.replace(/\._S[XY]\d+(_[^.]*)?\./, ".");
}

async function pageLooksBlocked(page) {
  if (await page.locator("#ap_login_form").count().catch(() => 0)) {
    return true;
  }
  const bodyText = await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
  return TERMINAL_BLOCK_PATTERNS.some((pattern) => pattern.test(bodyText));
}

async function scrapeReviewPage(page, { asin, domain, pageNumber, timeoutMs }) {
  const url = reviewPageUrl(domain, asin, pageNumber);
  const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch((error) => {
    error.scrapeUrl = url;
    throw error;
  });
  await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
  await page.waitForSelector("[data-hook='review'], [data-hook='cr-filter-info-review-rating-count'], #cm_cr-review_list, body", {
    timeout: 10000,
  }).catch(() => {});

  if (await pageLooksBlocked(page)) {
    return {
      status: "BLOCKED",
      statusCode: response?.status() || null,
      pageNumber,
      url,
      reviews: [],
    };
  }

    const reviews = await page.$$eval("[data-hook='review']", (nodes) => nodes.map((node) => {
    const text = (selector) => node.querySelector(selector)?.textContent?.trim() || "";
    const attr = (selector, name) => node.querySelector(selector)?.getAttribute(name) || "";
    const reviewId = node.getAttribute("id") || node.getAttribute("data-review-id") || "";
    const variationHref = attr("[data-hook='format-strip'] a", "href");
    const variationId = variationHref.match(/\/product-reviews\/([A-Z0-9]{10})/)?.[1] || "";
    const imageUrlList = Array.from(node.querySelectorAll("[data-hook='review-image-tile'], .review-image-tile, img"))
      .map((img) => img.getAttribute("src") || img.getAttribute("data-src") || "")
      .filter((src) => src.includes("media-amazon.com/images/I/"));

    return {
      reviewId,
      title: text("[data-hook='review-title']"),
      rating: text("[data-hook='review-star-rating'], [data-hook='cmps-review-star-rating']"),
      date: text("[data-hook='review-date']"),
      sizeColor: text("[data-hook='format-strip']"),
      text: text("[data-hook='review-body']"),
      userName: text(".a-profile-name"),
      profileUrl: attr(".a-profile", "href"),
      reviewUrl: attr("[data-hook='review-title']", "href"),
      numberOfHelpful: text("[data-hook='helpful-vote-statement']"),
      verifiedPurchase: text("[data-hook='avp-badge']"),
      variationId,
      imageUrlList,
    };
  }));

  return {
    status: reviews.length ? "FOUND" : "NO_REVIEWS",
    statusCode: response?.status() || null,
    pageNumber,
    url,
    reviews,
  };
}

async function scrapeAsin(page, options) {
  const allRows = [];
  let blocked = false;

  for (let pageNumber = 1; pageNumber <= options.maxPages; pageNumber += 1) {
    const result = await scrapeReviewPage(page, { ...options, pageNumber });

    if (result.status === "BLOCKED") {
      await writeDebugSnapshot(page, options, pageNumber, "blocked");
      allRows.push({
        statusCode: result.statusCode,
        statusMessage: "BLOCKED_OR_AUTH_WALL",
        asin: options.asin,
        domainCode: "com",
        currentPage: pageNumber,
        sourceUrl: result.url,
      });
      blocked = true;
      break;
    }

    if (result.reviews.length === 0) {
      await writeDebugSnapshot(page, options, pageNumber, "no_reviews");
      allRows.push({
        statusCode: result.statusCode,
        statusMessage: "NO_REVIEWS",
        asin: options.asin,
        domainCode: "com",
        currentPage: pageNumber,
        sourceUrl: result.url,
      });
      break;
    }

    for (const review of result.reviews) {
      const imageUrlList = [...new Set(review.imageUrlList.map(normalizeImageUrl).filter(Boolean))];
      if (!imageUrlList.length) continue;
      allRows.push({
        statusCode: result.statusCode,
        statusMessage: "FOUND",
        asin: options.asin,
        domainCode: "com",
        productTitle: await page.title().catch(() => ""),
        currentPage: pageNumber,
        sortStrategy: "recent",
        filters: {
          reviewerType: "all_reviews",
          mediaType: "media_reviews_only",
          formatType: "current_format",
        },
        reviewId: review.reviewId,
        text: review.text,
        date: review.date,
        rating: review.rating,
        title: review.title,
        userName: review.userName,
        profileUrl: review.profileUrl,
        reviewUrl: review.reviewUrl,
        numberOfHelpful: review.numberOfHelpful,
        sizeColor: review.sizeColor,
        verifiedPurchase: review.verifiedPurchase,
        variationId: review.variationId,
        imageUrlList,
        sourceUrl: result.url,
        scrapedAt: new Date().toISOString(),
      });
    }

    await sleep(options.sleepMs);
  }

  return { rows: dedupeRows(allRows), blocked };
}

async function writeDebugSnapshot(page, options, pageNumber, reason) {
  if (!options.debugDir) return;
  fs.mkdirSync(options.debugDir, { recursive: true });
  const filePath = path.join(options.debugDir, `${options.asin}_page_${pageNumber}_${reason}.html`);
  const html = await page.content().catch(() => "");
  fs.writeFileSync(filePath, html, "utf8");
}

function dedupeRows(rows) {
  const seen = new Set();
  const deduped = [];
  for (const row of rows) {
    const key = row.reviewId ? `${row.reviewId}:${row.variationId || ""}` : `${row.statusMessage}:${row.asin}:${row.currentPage}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(row);
  }
  return deduped;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const asins = args.csvPath
    ? loadAsins(args.csvPath, args.limit)
    : normalizeAsins(args.asins, args.limit);
  const batches = chunked(asins, args.batchSize);
  const firstBatchNumber = args.startBatchNumber || nextBatchNumber(args.outputDir);

  fs.mkdirSync(args.outputDir, { recursive: true });
  console.log(`Loaded ${asins.length} ASINs${args.csvPath ? ` from ${args.csvPath}` : ""}`);
  console.log(`Writing direct Amazon output to ${args.outputDir}`);
  console.log(`Starting at batch number ${String(firstBatchNumber).padStart(3, "0")}`);

  const browser = await chromium.launch({ headless: !args.headed });
  const context = await browser.newContext({
    locale: "en-US",
    timezoneId: "America/New_York",
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    viewport: { width: 1365, height: 900 },
  });
  const page = await context.newPage();

  let shouldStop = false;
  try {
    for (let batchIndex = 0; batchIndex < batches.length; batchIndex += 1) {
      const batchNumber = firstBatchNumber + batchIndex;
      const outputPath = batchPath(args.outputDir, batchNumber);
      const runPath = metadataPath(args.outputDir, batchNumber);
      const batchAsins = batches[batchIndex];

      if (fs.existsSync(outputPath)) {
        console.log(`[Batch ${batchIndex + 1}/${batches.length} | file ${String(batchNumber).padStart(3, "0")}] Output exists. Skipping.`);
        continue;
      }

      const metadata = {
        batchNumber,
        status: "RUNNING",
        startedAt: new Date().toISOString(),
        batchAsins,
        scraper: "direct_playwright",
        maxPages: args.maxPages,
        sleepMs: args.sleepMs,
      };
      writeJson(runPath, metadata);

      const rows = [];
      for (const [asinIndex, asin] of batchAsins.entries()) {
        console.log(`[Batch ${batchIndex + 1}/${batches.length} | ASIN ${asinIndex + 1}/${batchAsins.length}] Scraping ${asin}`);
        const result = await scrapeAsin(page, {
          asin,
          domain: args.domain,
          maxPages: args.maxPages,
          sleepMs: args.sleepMs,
          timeoutMs: args.pageTimeoutMs,
          debugDir: args.debugDir,
        });
        rows.push(...result.rows);

        if (result.blocked) {
          console.log(`Amazon returned a bot/CAPTCHA page for ${asin}; stopping this run without trying to bypass it.`);
          shouldStop = true;
          break;
        }

        await sleep(args.sleepMs);
      }

      writeJson(outputPath, rows);
      writeJson(runPath, {
        ...metadata,
        status: shouldStop ? "STOPPED_BLOCKED" : "SUCCEEDED",
        finishedAt: new Date().toISOString(),
        savedItemCount: rows.length,
        foundReviewCount: rows.filter((row) => row.statusMessage === "FOUND").length,
      });

      console.log(`[Batch ${batchIndex + 1}/${batches.length} | file ${String(batchNumber).padStart(3, "0")}] Saved ${rows.length} rows to ${outputPath}`);
      if (shouldStop) break;
    }
  } finally {
    if (args.keepBrowserOpen && args.headed) {
      console.log("Leaving headed browser open. Press Ctrl+C to exit when done.");
      await new Promise(() => {});
    }
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
