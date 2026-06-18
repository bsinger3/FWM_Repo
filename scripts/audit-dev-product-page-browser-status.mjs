#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const limit = Math.max(1, Number(parseArg("limit", "10")) || 10);
const browserTimeoutMs = Math.max(3000, Number(parseArg("browser-timeout-ms", "15000")) || 15000);
const perDomainDelayMs = Math.max(0, Number(parseArg("per-domain-delay-ms", "1000")) || 1000);
const maxPerDomain = Math.max(1, Number(parseArg("max-per-domain", "2")) || 2);
const statusReportPath = parseArg("status-report");
const buckets = new Set(
  String(parseArg("buckets", "robots_disallowed,blocked_or_forbidden,timeout,unknown,redirected_to_non_product"))
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);
const userAgent = parseArg("user-agent", "FWMDevBrowserStatusAudit/0.1 (+https://friendswithmeasurements.com)");
const BROWSER_CHECKER_VERSION = "product_page_status_browser_playwright_v1";

const lastDomainFetchAt = new Map();

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
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

function candidateSql() {
  const bucketList = Array.from(buckets).map(sqlString).join(", ");
  return `
select coalesce(jsonb_agg(row_to_json(candidate) order by candidate.normalized_product_page_url), '[]'::jsonb)
from (
  select
    id::text as product_page_id,
    normalized_product_page_url,
    source_status,
    source_status_evidence,
    source_status_error,
    robots_disallowed,
    source_final_url,
    source_final_url_type
  from staging.product_pages
  where normalized_product_page_url is not null
    and source_status in (${bucketList || "'blocked_or_forbidden'"})
  order by source_status_checked_at nulls first, normalized_product_page_url
  limit ${limit * 5}
) candidate;`;
}

async function loadCandidatesFromStatusReport(filePath) {
  const report = JSON.parse(await readFile(path.resolve(filePath), "utf8"));
  const results = Array.isArray(report.results) ? report.results : [];
  return results
    .filter((result) => buckets.has(result.source_status))
    .map((result) => ({
      product_page_id: result.product_page_id,
      normalized_product_page_url: result.normalized_product_page_url,
      source_status: result.source_status,
      source_status_evidence: result.source_status_evidence,
      source_status_error: result.source_status_error,
      robots_disallowed: result.robots_disallowed,
      source_final_url: result.source_final_url,
      source_final_url_type: result.source_final_url_type,
      source_report_path: path.resolve(filePath),
    }));
}

function domainCapped(candidates) {
  const selected = [];
  const counts = new Map();
  for (const candidate of candidates) {
    let host = "invalid";
    try {
      host = new URL(candidate.normalized_product_page_url).hostname;
    } catch {
      // Keep invalid URLs in the review output.
    }
    const count = counts.get(host) || 0;
    if (count >= maxPerDomain) continue;
    counts.set(host, count + 1);
    selected.push(candidate);
    if (selected.length >= limit) break;
  }
  return selected;
}

async function respectDomainDelay(url) {
  const host = new URL(url).hostname;
  const last = lastDomainFetchAt.get(host) || 0;
  const waitMs = Math.max(0, perDomainDelayMs - (Date.now() - last));
  if (waitMs) await sleep(waitMs);
  lastDomainFetchAt.set(host, Date.now());
}

function classifyVisiblePage({ finalUrl, title, text }) {
  const lowerUrl = String(finalUrl || "").toLowerCase();
  const lowerText = String(`${title}\n${text}` || "").toLowerCase().slice(0, 200000);
  if (/captcha|verify you are human|access denied|bot detection|blocked|cf-chl|cloudflare/.test(lowerText)) {
    return {
      browser_status: "human_review",
      browser_final_url_type: "blocked",
      evidence: "browser-visible captcha/bot/access-denied text",
      human_review_reason: "captcha_or_block_page",
    };
  }
  if (/page not found|404 not found|product not found/.test(lowerText)) {
    return {
      browser_status: "page_not_found",
      browser_final_url_type: "unknown",
      evidence: "browser-visible page-not-found text",
      human_review_reason: null,
    };
  }
  if (/out of stock|sold out|currently unavailable/.test(lowerText)) {
    return {
      browser_status: "out_of_stock",
      browser_final_url_type: "product",
      evidence: "browser-visible out-of-stock text",
      human_review_reason: null,
    };
  }
  if (/no longer available|discontinued|removed from our site/.test(lowerText)) {
    return {
      browser_status: "product_unavailable",
      browser_final_url_type: "product",
      evidence: "browser-visible unavailable/discontinued text",
      human_review_reason: null,
    };
  }
  if (/\/products?\//.test(lowerUrl) || /add to cart|add-to-cart|size|color|sku|variant/.test(lowerText)) {
    return {
      browser_status: "live",
      browser_final_url_type: "product",
      evidence: "browser-visible product-like page signals",
      human_review_reason: null,
    };
  }
  if (/\/collections?\//.test(lowerUrl) || /\/search|\/account|\/login/.test(lowerUrl)) {
    return {
      browser_status: "redirected_to_non_product",
      browser_final_url_type: "non_product",
      evidence: "browser final URL looks non-product",
      human_review_reason: null,
    };
  }
  return {
    browser_status: "human_review",
    browser_final_url_type: "unknown",
    evidence: "browser loaded but product status is unclear",
    human_review_reason: "unclear_browser_page",
  };
}

async function auditOne(page, candidate, screenshotsDir) {
  const base = {
    product_page_id: candidate.product_page_id,
    normalized_product_page_url: candidate.normalized_product_page_url,
    previous_source_status: candidate.source_status,
    previous_source_status_evidence: candidate.source_status_evidence,
    previous_source_status_error: candidate.source_status_error,
    previous_source_final_url: candidate.source_final_url,
    previous_source_final_url_type: candidate.source_final_url_type,
    browser_checked_at: new Date().toISOString(),
    browser_checker_version: BROWSER_CHECKER_VERSION,
  };
  if (candidate.robots_disallowed || candidate.source_status === "robots_disallowed") {
    return {
      ...base,
      skipped_browser: true,
      browser_status: "human_review",
      browser_final_url_type: "unknown",
      browser_status_evidence: candidate.source_status_evidence || "robots disallowed",
      human_review_reason: "robots_disallowed",
    };
  }
  let parsed;
  try {
    parsed = new URL(candidate.normalized_product_page_url);
  } catch {
    return {
      ...base,
      skipped_browser: true,
      browser_status: "human_review",
      browser_final_url_type: "unknown",
      browser_status_evidence: "invalid url",
      human_review_reason: "invalid_url",
    };
  }

  await respectDomainDelay(parsed.href);
  try {
    const response = await page.goto(parsed.href, {
      waitUntil: "domcontentloaded",
      timeout: browserTimeoutMs,
    });
    try {
      await page.waitForLoadState("networkidle", { timeout: Math.min(5000, browserTimeoutMs) });
    } catch {
      // Many retail pages keep analytics connections open; DOM content is enough for a review pass.
    }
    const title = await page.title();
    const visibleText = await page.locator("body").innerText({ timeout: 3000 }).catch(() => "");
    const finalUrl = page.url();
    const classified = classifyVisiblePage({ finalUrl, title, text: visibleText });
    const screenshotPath = path.join(screenshotsDir, `${candidate.product_page_id || encodeURIComponent(parsed.hostname)}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: false }).catch(() => null);
    return {
      ...base,
      skipped_browser: false,
      browser_http_status: response?.status() ?? null,
      browser_final_url: finalUrl,
      browser_title: title,
      browser_status: classified.browser_status,
      browser_final_url_type: classified.browser_final_url_type,
      browser_status_evidence: classified.evidence,
      human_review_reason: classified.human_review_reason,
      screenshot_path: screenshotPath,
      visible_text_sample: visibleText.slice(0, 1500),
    };
  } catch (error) {
    return {
      ...base,
      skipped_browser: false,
      browser_http_status: null,
      browser_final_url: null,
      browser_title: null,
      browser_status: "human_review",
      browser_final_url_type: "unknown",
      browser_status_evidence: "browser navigation failed",
      browser_status_error: String(error?.message || error),
      human_review_reason: "browser_navigation_failed",
    };
  }
}

function summarize(results) {
  const byStatus = {};
  const humanReviewByReason = {};
  for (const result of results) {
    byStatus[result.browser_status] = (byStatus[result.browser_status] || 0) + 1;
    if (result.human_review_reason) {
      humanReviewByReason[result.human_review_reason] = (humanReviewByReason[result.human_review_reason] || 0) + 1;
    }
  }
  return { byStatus, humanReviewByReason };
}

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function buildReviewHtml(report) {
  const cards = report.results
    .map((result) => `
      <article class="card ${htmlEscape(result.browser_status)}">
        <h2><a href="${htmlEscape(result.normalized_product_page_url)}" target="_blank" rel="noreferrer">${htmlEscape(result.normalized_product_page_url)}</a></h2>
        <div class="pills">
          <span>previous: ${htmlEscape(result.previous_source_status)}</span>
          <span>browser: ${htmlEscape(result.browser_status)}</span>
          <span>${htmlEscape(result.browser_final_url_type)}</span>
          ${result.human_review_reason ? `<span>human review: ${htmlEscape(result.human_review_reason)}</span>` : ""}
        </div>
        ${result.screenshot_path ? `<img src="${htmlEscape(result.screenshot_path)}" loading="lazy">` : ""}
        <dl>
          <dt>Browser final URL</dt>
          <dd>${result.browser_final_url ? `<a href="${htmlEscape(result.browser_final_url)}" target="_blank" rel="noreferrer">${htmlEscape(result.browser_final_url)}</a>` : "none"}</dd>
          <dt>Title</dt>
          <dd>${htmlEscape(result.browser_title || "")}</dd>
          <dt>Browser evidence</dt>
          <dd>${htmlEscape(result.browser_status_evidence)}</dd>
          <dt>Previous evidence</dt>
          <dd>${htmlEscape(result.previous_source_status_evidence || "")}</dd>
        </dl>
        <details>
          <summary>Visible text sample</summary>
          <pre>${htmlEscape(result.visible_text_sample || "")}</pre>
        </details>
      </article>`)
    .join("\n");
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FWM Dev Browser Status Audit</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; color: #1f2933; }
    header { margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); gap: 16px; }
    .card { border: 1px solid #d9e2ec; border-radius: 8px; padding: 14px; background: #fff; }
    .human_review { border-color: #f08c00; }
    .live { border-color: #2f9e44; }
    h2 { font-size: 14px; overflow-wrap: anywhere; }
    .pills { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 12px; }
    .pills span { background: #f0f4f8; border-radius: 999px; padding: 4px 8px; font-size: 12px; }
    img { max-width: 100%; border: 1px solid #d9e2ec; border-radius: 4px; background: #f8fafc; }
    dt { font-weight: 700; margin-top: 8px; }
    dd { margin-left: 0; overflow-wrap: anywhere; color: #334e68; }
    pre { white-space: pre-wrap; font-size: 11px; background: #f8fafc; padding: 8px; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <header>
    <h1>FWM Dev Browser Status Audit</h1>
    <p>Generated ${htmlEscape(report.generated_at)}. Mode: dry-run. Candidates: ${htmlEscape(report.candidate_count)}.</p>
    <pre>${htmlEscape(JSON.stringify(report.summary, null, 2))}</pre>
  </header>
  <main class="grid">${cards}</main>
</body>
</html>
`;
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (!/[",\n\r]/.test(text)) return text;
  return `"${text.replaceAll('"', '""')}"`;
}

function buildHumanReviewCsv(report) {
  const rows = (report.results || []).filter((result) => result.human_review_reason);
  const header = [
    "product_page_id",
    "normalized_product_page_url",
    "previous_source_status",
    "browser_status",
    "human_review_reason",
    "browser_final_url",
    "browser_title",
    "browser_status_evidence",
    "previous_source_status_evidence",
    "screenshot_path",
  ];
  return [
    header.join(","),
    ...rows.map((result) =>
      header.map((field) => csvEscape(result[field])).join(","),
    ),
  ].join("\n") + "\n";
}

async function loadCandidates() {
  if (statusReportPath) return loadCandidatesFromStatusReport(statusReportPath);
  return parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, candidateSql()));
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Browser status audit guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const candidatePool = await loadCandidates();
  const candidates = domainCapped(candidatePool);
  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  const reportStem = `dev_product_page_browser_status_audit_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const screenshotsDir = path.join(reportsDir, `${reportStem}_screenshots`);
  await mkdir(screenshotsDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent,
    viewport: { width: 1280, height: 900 },
  });
  const page = await context.newPage();
  const results = [];
  try {
    for (const candidate of candidates) {
      results.push(await auditOne(page, candidate, screenshotsDir));
    }
  } finally {
    await browser.close();
  }

  const reportPath = path.join(reportsDir, `${reportStem}.json`);
  const reviewHtmlPath = path.join(reportsDir, `${reportStem}.html`);
  const humanReviewCsvPath = path.join(reportsDir, `${reportStem}_human_review.csv`);
  const summary = summarize(results);
  const report = {
    generated_at: generatedAt,
    mode: "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    browser_checker_version: BROWSER_CHECKER_VERSION,
    user_agent: userAgent,
    status_report_path: statusReportPath ? path.resolve(statusReportPath) : null,
    selected_buckets: Array.from(buckets),
    limit,
    browser_timeout_ms: browserTimeoutMs,
    per_domain_delay_ms: perDomainDelayMs,
    max_per_domain: maxPerDomain,
    candidate_pool_count: candidatePool.length,
    candidate_count: candidates.length,
    summary,
    review_html_path: reviewHtmlPath,
    human_review_csv_path: humanReviewCsvPath,
    screenshots_dir: screenshotsDir,
    results,
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(reviewHtmlPath, buildReviewHtml(report), "utf8");
  await writeFile(humanReviewCsvPath, buildHumanReviewCsv(report), "utf8");
  console.log(`Wrote browser status audit report: ${reportPath}`);
  console.log(`Wrote browser status review HTML: ${reviewHtmlPath}`);
  console.log(`Wrote browser status human-review CSV: ${humanReviewCsvPath}`);
  console.log(`Mode: dry-run`);
  console.log(`Candidates audited: ${report.candidate_count}`);
  console.log(`Summary: ${JSON.stringify(summary)}`);
  console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
