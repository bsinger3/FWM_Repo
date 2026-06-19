#!/usr/bin/env node
/**
 * FREE Amazon product-page taxonomy backfill — no Apify, no proxy, no Playwright.
 *
 * Iterates the work-list built by scripts/build-amazon-taxonomy-worklist.mjs,
 * does a plain HTTP GET of the canonical https://www.amazon.com/dp/{ASIN} URL
 * with a normal desktop Chrome User-Agent, parses the wayfinding breadcrumb,
 * Best Sellers Rank category, and product title, and maps them to a
 * mother_category_id + clothing_type item tags by REUSING the existing
 * classifier (extractTaxonomy) from audit-dev-product-page-taxonomy.mjs.
 *
 * --- Amazon ToS note ---------------------------------------------------------
 * Amazon's Conditions of Use discourage scraping. This is a ONE-TIME, low-volume,
 * read-only backfill (one polite GET per page of the canonical /dp/{ASIN} URL,
 * which robots.txt for User-agent:* does not disallow). The compliant structured
 * alternative is the Amazon Product Advertising API (BrowseNodes / GetItems) if
 * an Associates account exists; prefer that for any ongoing/repeated use.
 * -----------------------------------------------------------------------------
 *
 * Output: an audit-shaped report
 *   FWM_Data/_reports/dev_product_page_taxonomy_audit_amazon_free_<ts>.json
 * (top-level metadata + results[] where each non-skipped row carries
 *  proposed.primaryCategory{...} + proposed.itemTags[]) so it flows straight into
 *  the existing  promote-dev-taxonomy-results.mjs --taxonomy-report=<this>  →
 *  taxonomy-review dashboard → --apply  loop with no new plumbing.
 *
 * DEFAULT: report-only / dry-run. No Supabase writes. Humans approve in the
 * dashboard before promotion.
 *
 * Resumable: every fetched page is appended to a progress NDJSON sidecar; on
 * restart, product_page_ids already present there are skipped.
 *
 * Usage:
 *   node scripts/backfill-amazon-taxonomy-free.mjs                # full run, newest work-list
 *   node scripts/backfill-amazon-taxonomy-free.mjs --limit=25     # small test batch
 *   node scripts/backfill-amazon-taxonomy-free.mjs --worklist=/abs/path.ndjson
 *   node scripts/backfill-amazon-taxonomy-free.mjs --delay-min-ms=2000 --delay-max-ms=4000
 */

import { readdir, readFile, appendFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync, createReadStream } from "node:fs";
import { createInterface } from "node:readline";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  extractTaxonomy,
  catalogFromFields,
  stripTags,
  normalizeBrowserBreadcrumb,
} from "./audit-dev-product-page-taxonomy.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

const EXTRACTOR_VERSION = "product_page_taxonomy_rules_v7_amazon_free_http_fetch";
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36";

function parseArg(name, fallback = "") {
  const prefix = `--${name}=`;
  const hit = process.argv.find((arg) => arg.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}
function numArg(name, fallback) {
  const raw = parseArg(name, "");
  if (raw === "") return fallback; // not provided — Number("") is 0, so guard explicitly
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

const limit = Math.max(0, Math.floor(numArg("limit", 0))); // 0 = no cap
const timeoutMs = Math.max(1000, numArg("timeout-ms", 20000));
const delayMinMs = Math.max(0, numArg("delay-min-ms", 2000));
const delayMaxMs = Math.max(delayMinMs, numArg("delay-max-ms", 4000));
const maxRetries = Math.max(0, Math.floor(numArg("max-retries", 5)));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// Deterministic-enough jitter without Math.random gating; fine for politeness.
function jitterDelay() {
  const span = delayMaxMs - delayMinMs;
  const frac = (Date.now() % 1000) / 1000;
  return Math.round(delayMinMs + span * frac);
}

async function latestWorklistPath(reportsDir) {
  // Match only the work-list itself (timestamped), NOT its *_progress.ndjson sidecar.
  const files = (await readdir(reportsDir))
    .filter((f) => /^amazon_taxonomy_worklist_\d{8}T\d{6}\d{3}Z\.ndjson$/.test(f))
    .sort();
  if (!files.length) {
    throw new Error(
      `No amazon_taxonomy_worklist_*.ndjson in ${reportsDir}. ` +
        `Run: node scripts/build-amazon-taxonomy-worklist.mjs`,
    );
  }
  return path.join(reportsDir, files[files.length - 1]);
}

async function readNdjson(filePath) {
  const raw = await readFile(filePath, "utf8");
  const rows = [];
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    try {
      rows.push(JSON.parse(line));
    } catch {
      /* skip malformed line */
    }
  }
  return rows;
}

// Load already-processed product_page_ids and their stored result rows from the
// progress sidecar so a re-run resumes instead of refetching.
async function loadProgress(progressPath) {
  const byId = new Map();
  if (!existsSync(progressPath)) return byId;
  const stream = createInterface({ input: createReadStream(progressPath), crlfDelay: Infinity });
  for await (const line of stream) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      if (row.product_page_id) byId.set(row.product_page_id, row);
    } catch {
      /* skip malformed line */
    }
  }
  return byId;
}

// ---- Amazon HTML field extraction ------------------------------------------

function decodeBasicEntities(value) {
  // stripTags already runs decodeHtml; this is a light pre-clean for &#39; etc.
  return String(value || "");
}

function parseProductTitle(html) {
  const direct = html.match(/<span[^>]*id="productTitle"[^>]*>([\s\S]*?)<\/span>/i);
  if (direct) return stripTags(direct[1]);
  const og = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i);
  if (og) return stripTags(og[1]);
  const title = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (title) {
    return stripTags(title[1])
      .replace(/\s*[:|-]\s*Amazon\.com.*$/i, "")
      .replace(/^Amazon\.com\s*[:|-]\s*/i, "")
      .trim();
  }
  return "";
}

function parseBreadcrumb(html) {
  const block = html.match(
    /<div[^>]*id="wayfinding-breadcrumbs_feature_div"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/i,
  );
  if (!block) return "";
  // Breadcrumb anchors carry class a-link-normal a-color-tertiary; fall back to
  // any anchor text inside the wayfinding block if Amazon tweaks the class list.
  let parts = [...block[1].matchAll(/<a[^>]+class="[^"]*a-color-tertiary[^"]*"[^>]*>([\s\S]*?)<\/a>/gi)]
    .map((m) => stripTags(m[1]))
    .filter(Boolean);
  if (!parts.length) {
    parts = [...block[1].matchAll(/<a[^>]*>([\s\S]*?)<\/a>/gi)].map((m) => stripTags(m[1])).filter(Boolean);
  }
  return normalizeBrowserBreadcrumb(parts.join("\n"));
}

// Best Sellers Rank category phrases, e.g. "#5 in Women's Jeans" -> "Women's Jeans".
// These are reliable category signals; emitted as a supplementary (medium) field.
function parseBsrCategories(html) {
  const idx = html.search(/Best Sellers Rank/i);
  if (idx === -1) return "";
  const window = html.slice(idx, idx + 2000);
  const text = stripTags(window);
  const cats = [...text.matchAll(/#[\d,]+\s+in\s+([^#()]+?)(?:\s*\(|#|\bASIN\b|$)/gi)]
    .map((m) => m[1].trim())
    .filter((c) => c && !/^our brands$/i.test(c) && c.length < 80);
  return [...new Set(cats)].join(" ; ");
}

function isCaptchaOrBlock(status, html) {
  if (status === 503 || status === 429) return true;
  const lower = html.slice(0, 20000).toLowerCase();
  return (
    lower.includes("/errors/validatecaptcha") ||
    lower.includes("api-services-support@amazon.com") ||
    lower.includes("enter the characters you see below") ||
    lower.includes("type the characters you see") ||
    lower.includes("to discuss automated access")
  );
}

async function fetchHtml(url) {
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
    const html = await response.text();
    return { status: response.status, finalUrl: response.url || url, html };
  } finally {
    clearTimeout(timer);
  }
}

function buildFields(html, normalizedUrl) {
  const title = parseProductTitle(html);
  const breadcrumb = parseBreadcrumb(html);
  const bsr = parseBsrCategories(html);
  let urlSlug = "";
  try {
    urlSlug = stripTags(decodeURIComponent(new URL(normalizedUrl).pathname).replace(/[-_/]+/g, " "));
  } catch {
    urlSlug = "";
  }
  return {
    json_ld_product_core: "",
    json_ld_product_description: "",
    title,
    breadcrumb,
    // BSR category phrases live in the medium-confidence description field so the
    // high-confidence breadcrumb/title stay authoritative and BSR only fills gaps.
    description: bsr,
    url_slug: urlSlug,
    catalog_image_url: "",
    catalog_image_urls: [],
    catalog_image_source: "",
    catalog_image_fetch_status: "not_fetched",
    workbook_fallback: "",
    json_ld_parse_error_count: 0,
  };
}

// Process a single work-list entry, with retry/backoff on block pages.
async function processPage(entry) {
  const base = {
    product_page_id: entry.product_page_id,
    normalized_product_page_url: entry.normalized_product_page_url,
    asin: entry.asin,
    canonical_url: entry.canonical_url,
    source: "amazon_free_http_fetch",
  };

  let attempt = 0;
  while (true) {
    let result;
    try {
      result = await fetchHtml(entry.canonical_url);
    } catch (error) {
      const isTimeout = error?.name === "AbortError";
      if (attempt < maxRetries) {
        attempt += 1;
        const backoff = Math.min(120000, 5000 * 2 ** (attempt - 1));
        console.warn(`  ${entry.asin}: ${isTimeout ? "timeout" : "fetch error"} (${error?.message || error}); retry ${attempt}/${maxRetries} after ${Math.round(backoff / 1000)}s`);
        await sleep(backoff);
        continue;
      }
      return { ...base, skipped: true, skip_reason: isTimeout ? "timeout" : "fetch_error", error: String(error?.message || error) };
    }

    const { status, finalUrl, html } = result;

    if (isCaptchaOrBlock(status, html)) {
      if (attempt < maxRetries) {
        attempt += 1;
        const backoff = Math.min(180000, 30000 * 2 ** (attempt - 1));
        console.warn(`  ${entry.asin}: blocked (status ${status}); backoff ${Math.round(backoff / 1000)}s, retry ${attempt}/${maxRetries}`);
        await sleep(backoff);
        continue;
      }
      return { ...base, skipped: true, skip_reason: "captcha_or_block", http_status: status, final_url: finalUrl };
    }

    if (status >= 400) {
      return { ...base, skipped: true, skip_reason: `http_status_${status}`, http_status: status, final_url: finalUrl };
    }

    const fields = buildFields(html, entry.normalized_product_page_url);
    if (!fields.title && !fields.breadcrumb && !fields.description) {
      return { ...base, skipped: true, skip_reason: "no_usable_fields", http_status: status, final_url: finalUrl };
    }

    const taxonomy = extractTaxonomy(fields);
    return {
      ...base,
      skipped: false,
      http_status: status,
      final_url: finalUrl,
      extracted_fields_preview: Object.fromEntries(
        ["title", "breadcrumb", "description", "url_slug"].map((k) => [k, String(fields[k] || "").slice(0, 500)]),
      ),
      catalog: catalogFromFields(fields),
      proposed: taxonomy,
    };
  }
}

function summarize(results) {
  const summary = {
    total: results.length,
    skipped: 0,
    skip_reasons: {},
    proposed_primary_categories: {},
    ambiguous_primary_categories: 0,
    proposed_item_tag_count: 0,
    no_category: 0,
  };
  for (const r of results) {
    if (r.skipped) {
      summary.skipped += 1;
      summary.skip_reasons[r.skip_reason] = (summary.skip_reasons[r.skip_reason] || 0) + 1;
      continue;
    }
    if (r.proposed?.categoryAmbiguous) summary.ambiguous_primary_categories += 1;
    const cat = r.proposed?.primaryCategory?.mother_category_id;
    if (cat) summary.proposed_primary_categories[cat] = (summary.proposed_primary_categories[cat] || 0) + 1;
    else summary.no_category += 1;
    summary.proposed_item_tag_count += r.proposed?.itemTags?.length || 0;
  }
  return summary;
}

async function main() {
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });

  const worklistPath = parseArg("worklist")
    ? path.resolve(parseArg("worklist"))
    : await latestWorklistPath(reportsDir);
  const worklist = await readNdjson(worklistPath);
  const worklistStem = path.basename(worklistPath).replace(/\.ndjson$/, "");
  const progressPath = path.join(reportsDir, `${worklistStem}_progress.ndjson`);

  const done = await loadProgress(progressPath);
  const pending = worklist.filter((e) => !done.has(e.product_page_id));
  const batch = limit > 0 ? pending.slice(0, limit) : pending;

  console.log(`Work-list:        ${worklistPath}`);
  console.log(`Progress sidecar: ${progressPath}`);
  console.log(`Total pages:      ${worklist.length}`);
  console.log(`Already done:     ${done.size}`);
  console.log(`Pending:          ${pending.length}`);
  console.log(`This run:         ${batch.length}${limit ? ` (--limit=${limit})` : ""}`);
  console.log(`Politeness:       ${delayMinMs}-${delayMaxMs}ms between requests, up to ${maxRetries} retries\n`);

  let processed = 0;
  for (const entry of batch) {
    const row = await processPage(entry);
    await appendFile(progressPath, JSON.stringify(row) + "\n", "utf8");
    done.set(row.product_page_id, row);
    processed += 1;
    const tag = row.skipped
      ? `SKIP ${row.skip_reason}`
      : row.proposed?.primaryCategory?.mother_category_id
        ? `${row.proposed.primaryCategory.mother_category_id} (${row.proposed.primaryCategory.category_confidence})`
        : "no-category";
    console.log(`[${processed}/${batch.length}] ${entry.asin} -> ${tag}`);
    if (processed < batch.length) await sleep(jitterDelay());
  }

  // Assemble the final audit-shaped report from ALL progress rows (resumable runs
  // accumulate across invocations).
  const results = Array.from(done.values());
  const stamp = new Date().toISOString();
  const report = {
    generated_at: stamp,
    mode: "dry-run",
    method: "amazon_free_http_fetch",
    amazon_tos_note:
      "Amazon Conditions of Use discourage scraping. One-time low-volume read-only backfill of the canonical /dp/{ASIN} URL (not robots-disallowed). Compliant alternative: Amazon Product Advertising API (BrowseNodes/GetItems) with an Associates account.",
    extractor_version: EXTRACTOR_VERSION,
    user_agent: USER_AGENT,
    worklist_path: worklistPath,
    progress_path: progressPath,
    timeout_ms: timeoutMs,
    delay_min_ms: delayMinMs,
    delay_max_ms: delayMaxMs,
    candidate_count: results.length,
    summary: summarize(results),
    results,
  };

  const reportStamp = stamp.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const reportPath = path.join(reportsDir, `dev_product_page_taxonomy_audit_amazon_free_${reportStamp}.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`\nWrote report -> ${reportPath}`);
  console.log(`Summary: ${JSON.stringify(report.summary)}`);
  console.log(`\nNext: review with the taxonomy dashboard, then promote:`);
  console.log(`  node scripts/promote-dev-taxonomy-results.mjs --taxonomy-report=${reportPath}`);
  console.log(`(dry-run only — no Supabase rows were written.)`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
