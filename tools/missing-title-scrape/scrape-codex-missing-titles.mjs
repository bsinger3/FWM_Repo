#!/usr/bin/env node
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const inputPath = path.join(toolDir, "codex-missing-titles-input.ndjson");
const outputPath = path.join(toolDir, "codex-missing-titles.result.ndjson");
const cacheDir = path.join(toolDir, ".title-scrape-cache");

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36";
const timeoutMs = Number(process.env.TITLE_SCRAPE_TIMEOUT_MS || 30000);
const defaultDelayMs = Number(process.env.TITLE_SCRAPE_DELAY_MS || 1100);
const bloomDelayMs = Number(process.env.TITLE_SCRAPE_BLOOMCHIC_DELAY_MS || 2500);
const retryStatuses = new Set([408, 425, 429, 500, 502, 503, 504]);

const limitArg = Number((process.argv.find((arg) => arg.startsWith("--limit=")) || "").split("=")[1] || 0);
const offsetArg = Number((process.argv.find((arg) => arg.startsWith("--offset=")) || "").split("=")[1] || 0);
const onlyHostArg = (process.argv.find((arg) => arg.startsWith("--host=")) || "").split("=")[1] || "";
const excludeHostArg = (process.argv.find((arg) => arg.startsWith("--exclude-host=")) || "").split("=")[1] || "";
const parallelHosts = Number((process.argv.find((arg) => arg.startsWith("--parallel-hosts=")) || "").split("=")[1] || 8);
const force = process.argv.includes("--force");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const lastFetchByHost = new Map();
const robotsCache = new Map();

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
  return decodeHtml(
    String(value || "")
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " "),
  )
    .replace(/\s+/g, " ")
    .trim();
}

function attrValue(tag, attr) {
  const match = String(tag || "").match(new RegExp(`${attr}\\s*=\\s*(["'])([\\s\\S]*?)\\1`, "i"));
  return match ? decodeHtml(match[2]) : "";
}

function metaContent(html, key) {
  const lowerKey = key.toLowerCase();
  for (const match of html.matchAll(/<meta\b[^>]*>/gi)) {
    const tag = match[0];
    const name = (attrValue(tag, "property") || attrValue(tag, "name") || attrValue(tag, "itemprop")).toLowerCase();
    if (name === lowerKey) return attrValue(tag, "content");
  }
  return "";
}

function titleTag(html) {
  return stripTags((html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1] || "");
}

function cleanTitle(title, url) {
  const host = new URL(url).hostname.replace(/^www\./, "");
  let value = stripTags(title)
    .replace(/\s+[|–-]\s+(Rent the Runway|Nuuly|Cider|BloomChic|RIHOAS|Chicwish|Shapermint|Berlook).*$/i, "")
    .replace(/\s*[:|-]\s*Amazon\.com.*$/i, "")
    .replace(/^Amazon\.com\s*[:|-]\s*/i, "")
    .replace(/\s+\|\s+.*$/i, "")
    .trim();
  if (host.includes("amazon")) value = value.replace(/\s*:\s*Clothing, Shoes & Jewelry\s*$/i, "").trim();
  return value;
}

function isBadTitle(title, html, status) {
  const value = String(title || "").trim();
  if (!value) return "no title found";
  if (status >= 400) return `http ${status}`;
  if (/captcha|robot check|enter the characters|sorry, we just need to make sure/i.test(`${value} ${html.slice(0, 3000)}`)) {
    return "captcha";
  }
  if (/^(access denied|forbidden|page not found|not found|just a moment|attention required)$/i.test(value)) {
    return "blocked or non-product title";
  }
  if (value.length < 3) return "title too short";
  return "";
}

function isCaptchaHtml(html, status) {
  return status === 503 || status === 429 || /captcha|robot check|enter the characters|sorry, we just need to make sure/i.test(String(html || "").slice(0, 20000));
}

function asText(value) {
  if (!value) return "";
  if (typeof value === "string") return stripTags(value);
  if (typeof value === "object") return asText(value.name || value["@id"] || value.title || value.text);
  return "";
}

function flattenJsonLd(value) {
  if (!value) return [];
  const roots = Array.isArray(value) ? value : [value];
  const out = [];
  for (const item of roots) {
    if (!item || typeof item !== "object") continue;
    out.push(item);
    if (Array.isArray(item["@graph"])) out.push(...flattenJsonLd(item["@graph"]));
  }
  return out;
}

function parseJsonLd(html) {
  const out = [];
  for (const match of html.matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    const raw = decodeHtml(match[1]).trim();
    if (!raw) continue;
    try {
      out.push(...flattenJsonLd(JSON.parse(raw)));
    } catch {
      // Retailer pages often include malformed analytics JSON-LD; meta tags are the fallback.
    }
  }
  return out;
}

function typeIncludes(item, needle) {
  const type = item?.["@type"];
  return type === needle || (Array.isArray(type) && type.includes(needle));
}

function extractInitialStateTitle(html, url) {
  const host = new URL(url).hostname;
  if (!host.includes("shopcider")) return "";
  const match = html.match(/window\.__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\})\s*<\/script>/);
  if (!match) return "";
  try {
    return stripTags(JSON.parse(match[1])?.storeState?.productionDetail?.productionDetail?.productName || "");
  } catch {
    return "";
  }
}

function extractAmazonTitle(html) {
  const direct = html.match(/<span[^>]*id=["']productTitle["'][^>]*>([\s\S]*?)<\/span>/i);
  return direct ? stripTags(direct[1]) : "";
}

function extractMetadata(html, url, seedBrand) {
  const jsonLd = parseJsonLd(html);
  const product = jsonLd.find((item) => typeIncludes(item, "Product")) || {};
  const breadcrumbs = jsonLd.find((item) => typeIncludes(item, "BreadcrumbList")) || {};
  const breadcrumbParts = Array.isArray(breadcrumbs.itemListElement)
    ? breadcrumbs.itemListElement.map((item) => asText(item?.item) || asText(item)).filter(Boolean)
    : [];

  const h1 = stripTags((html.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/i) || [])[1] || "");
  const title =
    asText(product.name) ||
    extractAmazonTitle(html) ||
    extractInitialStateTitle(html, url) ||
    h1 ||
    metaContent(html, "og:title") ||
    titleTag(html);

  const brand =
    seedBrand ||
    asText(product.brand) ||
    metaContent(html, "product:brand") ||
    metaContent(html, "brand") ||
    metaContent(html, "og:site_name");

  const breadcrumb =
    breadcrumbParts.join(" > ") ||
    asText(product.category) ||
    metaContent(html, "product:category") ||
    metaContent(html, "category");

  return {
    product_title: cleanTitle(title, url),
    brand: stripTags(brand),
    breadcrumb: stripTags(breadcrumb),
  };
}

async function readNdjson(filePath) {
  const rows = [];
  const stream = createInterface({ input: createReadStream(filePath), crlfDelay: Infinity });
  for await (const line of stream) {
    if (!line.trim()) continue;
    rows.push(JSON.parse(line));
  }
  return rows;
}

async function readExistingResults(filePath) {
  const done = new Set();
  try {
    await stat(filePath);
  } catch {
    return done;
  }
  const stream = createInterface({ input: createReadStream(filePath), crlfDelay: Infinity });
  for await (const line of stream) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      if (row.product_page_id) done.add(row.product_page_id);
    } catch {
      /* skip malformed partial lines */
    }
  }
  return done;
}

function cachePathForUrl(url) {
  const host = new URL(url).hostname.replace(/^www\./, "");
  const hash = createHash("sha256").update(url).digest("hex").slice(0, 24);
  return path.join(cacheDir, host, `${hash}.json`);
}

async function readCachedFetch(url) {
  try {
    return JSON.parse(await readFile(cachePathForUrl(url), "utf8"));
  } catch {
    return null;
  }
}

async function writeCachedFetch(url, data) {
  const filePath = cachePathForUrl(url);
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, JSON.stringify(data), "utf8");
}

function parseRobots(robotsText, targetUrl) {
  const target = new URL(targetUrl);
  const agents = [USER_AGENT.toLowerCase().split(/[ /;]/)[0], "*"];
  let currentAgents = [];
  let currentRules = [];
  const groups = [];
  const rules = [];

  function flushGroup() {
    if (!currentAgents.length && !currentRules.length) return;
    groups.push({ agents: currentAgents, rules: currentRules });
    currentAgents = [];
    currentRules = [];
  }

  for (const rawLine of String(robotsText || "").split(/\r?\n/)) {
    const line = rawLine.replace(/#.*/, "").trim();
    if (!line) {
      flushGroup();
      continue;
    }
    const sep = line.indexOf(":");
    if (sep === -1) continue;
    const key = line.slice(0, sep).trim().toLowerCase();
    const value = line.slice(sep + 1).trim();
    if (key === "user-agent") {
      if (currentRules.length) flushGroup();
      currentAgents.push(value.toLowerCase());
      continue;
    }
    if (key !== "allow" && key !== "disallow") continue;
    currentRules.push({ type: key, rule: value });
  }
  flushGroup();

  const matchingGroups = groups.filter((group) => group.agents.some((agent) => agents.includes(agent)));
  for (const group of matchingGroups) {
    for (const candidate of group.rules) {
      if (!candidate.rule) continue;
      const expression = candidate.rule
        .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
        .replace(/\*/g, ".*")
        .replace(/\$/g, "$");
      const regex = new RegExp(`^${expression}`);
      if (regex.test(target.pathname)) {
        rules.push({ ...candidate, length: candidate.rule.replace(/[*$]/g, "").length });
      }
    }
  }
  if (!rules.length) return { disallowed: false, rule: "" };
  rules.sort((a, b) => b.length - a.length);
  return { disallowed: rules[0].type === "disallow", rule: `${rules[0].type}: ${rules[0].rule}` };
}

async function respectHostDelay(url) {
  const host = new URL(url).hostname;
  const delayMs = host.includes("bloomchic") ? bloomDelayMs : defaultDelayMs;
  const last = lastFetchByHost.get(host) || 0;
  const waitMs = Math.max(0, delayMs - (Date.now() - last));
  if (waitMs) await sleep(waitMs);
  lastFetchByHost.set(host, Date.now());
}

async function fetchText(url) {
  await respectHostDelay(url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
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

async function robotsDecision(url) {
  const origin = new URL(url).origin;
  if (!robotsCache.has(origin)) {
    try {
      const response = await fetchText(`${origin}/robots.txt`);
      robotsCache.set(origin, { ok: response.status >= 200 && response.status < 300, text: response.html, error: response.status });
    } catch (error) {
      robotsCache.set(origin, { ok: false, text: "", error: error?.name === "AbortError" ? "timeout" : String(error?.message || error) });
    }
  }
  const robots = robotsCache.get(origin);
  if (!robots.ok) return { disallowed: false, rule: "", error: `robots ${robots.error}` };
  return { ...parseRobots(robots.text, url), error: "" };
}

async function fetchWithCache(url) {
  const cached = await readCachedFetch(url);
  if (cached && !isCaptchaHtml(cached.html, cached.status)) return { ...cached, fromCache: true };

  const robots = await robotsDecision(url);
  if (robots.disallowed) {
    return { status: 0, finalUrl: url, html: "", robots, fromCache: false };
  }

  let last = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      last = await fetchText(url);
      if (!retryStatuses.has(last.status)) break;
    } catch (error) {
      last = { status: 0, finalUrl: url, html: "", error: error?.name === "AbortError" ? "timeout" : String(error?.message || error) };
    }
    await sleep((attempt + 1) * 2000);
  }
  const cache = { ...last, fetched_at: new Date().toISOString() };
  if (!isCaptchaHtml(cache.html, cache.status)) await writeCachedFetch(url, cache);
  return { ...cache, fromCache: false };
}

function resultForFailure(row, httpStatus, note) {
  return {
    product_page_id: row.product_page_id,
    url: row.url,
    product_title: "",
    brand: row.brand || "",
    breadcrumb: "",
    scraped_ok: false,
    http_status: httpStatus || 0,
    note,
  };
}

function fetchUrlForRow(row) {
  const parsed = new URL(row.url);
  const asin = parsed.hostname.includes("amazon.com") ? parsed.pathname.match(/\/dp\/([A-Z0-9]{10})/i)?.[1] : "";
  if (asin) return `${parsed.origin}/dp/${asin.toUpperCase()}`;
  return row.url;
}

async function scrapeRow(row) {
  const fetchUrl = fetchUrlForRow(row);
  const fetched = await fetchWithCache(fetchUrl);
  if (fetched.robots?.disallowed) return resultForFailure(row, 0, `robots disallowed (${fetched.robots.rule})`);
  if (fetched.error) return resultForFailure(row, fetched.status, fetched.error);

  const metadata = extractMetadata(fetched.html || "", fetched.finalUrl || fetchUrl, row.brand);
  const failure = isBadTitle(metadata.product_title, fetched.html || "", fetched.status);
  if (failure) return resultForFailure(row, fetched.status, failure);

  return {
    product_page_id: row.product_page_id,
    url: row.url,
    product_title: metadata.product_title,
    brand: metadata.brand || row.brand || "",
    breadcrumb: metadata.breadcrumb || "",
    scraped_ok: true,
    http_status: fetched.status,
    note: fetched.fromCache ? "cache" : "",
  };
}

async function main() {
  await mkdir(cacheDir, { recursive: true });
  const allRows = await readNdjson(inputPath);
  const done = force ? new Set() : await readExistingResults(outputPath);
  let rows = allRows.filter((row) => !done.has(row.product_page_id));
  if (onlyHostArg) rows = rows.filter((row) => new URL(row.url).hostname.includes(onlyHostArg));
  if (excludeHostArg) rows = rows.filter((row) => !new URL(row.url).hostname.includes(excludeHostArg));
  if (offsetArg) rows = rows.slice(offsetArg);
  if (limitArg) rows = rows.slice(0, limitArg);

  console.log(`missing-title-scrape: input=${allRows.length} done=${done.size} queued=${rows.length} output=${path.relative(process.cwd(), outputPath)}`);
  const out = createWriteStream(outputPath, { flags: "a" });
  let ok = 0;
  let fail = 0;
  let completed = 0;
  const hostGroups = new Map();
  for (const row of rows) {
    const host = new URL(row.url).hostname;
    if (!hostGroups.has(host)) hostGroups.set(host, []);
    hostGroups.get(host).push(row);
  }
  const hostQueue = [...hostGroups.entries()].sort((a, b) => b[1].length - a[1].length);

  async function runHost(host, hostRows) {
    console.log(`missing-title-scrape: host ${host} queued=${hostRows.length}`);
    for (const row of hostRows) {
      let result;
      try {
        result = await scrapeRow(row);
      } catch (error) {
        result = resultForFailure(row, 0, error?.name === "AbortError" ? "timeout" : String(error?.message || error));
      }
      out.write(`${JSON.stringify(result)}\n`);
      if (result.scraped_ok) ok += 1;
      else fail += 1;
      completed += 1;
      if (completed % 25 === 0 || completed === rows.length) {
        console.log(`missing-title-scrape: progress ${completed}/${rows.length} ok=${ok} fail=${fail}`);
      }
    }
  }

  try {
    const workers = Array.from({ length: Math.max(1, Math.min(parallelHosts, hostQueue.length)) }, async () => {
      while (hostQueue.length) {
        const next = hostQueue.shift();
        if (!next) return;
        await runHost(next[0], next[1]);
      }
    });
    await Promise.all(workers);
  } finally {
    await new Promise((resolve) => out.end(resolve));
  }
  console.log(`missing-title-scrape: finished queued=${rows.length} ok=${ok} fail=${fail}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
