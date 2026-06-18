#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
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
const limit = Math.max(1, Number(parseArg("limit", "25")) || 25);
const onlyUnchecked = !process.argv.includes("--include-checked");
const timeoutMs = Math.max(1000, Number(parseArg("timeout-ms", "10000")) || 10000);
const perDomainDelayMs = Math.max(0, Number(parseArg("per-domain-delay-ms", "1000")) || 1000);
const maxPerDomain = Math.max(1, Number(parseArg("max-per-domain", "2")) || 2);
const userAgent = parseArg("user-agent", "FWMDevProductStatusAudit/0.1 (+https://friendswithmeasurements.com)");
const verifiedReportPath = parseArg("verified-report");
const productPageIdsFile = parseArg("product-page-ids-file");
const CHECKER_VERSION = "product_page_status_http_robots_v1";

const robotsCache = new Map();
const lastDomainFetchAt = new Map();

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

async function targetedProductPageIds() {
  if (!productPageIdsFile) return [];
  const raw = await readFile(path.resolve(productPageIdsFile), "utf8");
  return raw
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sqlString(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlBoolean(value) {
  if (value === null || value === undefined) return "null";
  return value ? "true" : "false";
}

function sqlNumber(value) {
  return Number.isFinite(value) ? String(value) : "null";
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
  if (!trimmed) return [];
  return JSON.parse(trimmed);
}

function candidateSql(targetedIds = []) {
  const targetedClause = targetedIds.length
    ? `and id::text in (${targetedIds.map(sqlString).join(",")})`
    : "";
  return `
select coalesce(jsonb_agg(row_to_json(candidate) order by candidate.normalized_product_page_url), '[]'::jsonb)
from (
  select *
  from (
    select
      id::text,
      normalized_product_page_url,
      source_status,
      source_status_checked_at,
      source_site,
      brand,
      product_title_raw,
      row_number() over (
        partition by lower(split_part(regexp_replace(normalized_product_page_url, '^https?://', ''), '/', 1))
        order by source_status_checked_at nulls first, normalized_product_page_url
      ) as host_rank
    from staging.product_pages
    where normalized_product_page_url is not null
      ${onlyUnchecked ? "and source_status_checked_at is null" : ""}
      ${targetedClause}
  ) ranked
  where host_rank <= ${maxPerDomain}
  order by source_status_checked_at nulls first, normalized_product_page_url
  limit ${limit}
) candidate;`;
}

function selectDomainCappedCandidates(candidates) {
  const selected = [];
  const counts = new Map();
  for (const candidate of candidates) {
    let host = "invalid";
    try {
      host = new URL(candidate.normalized_product_page_url).hostname;
    } catch {
      // Keep invalid URLs in the audit; they should be reported.
    }
    const count = counts.get(host) || 0;
    if (count >= maxPerDomain) continue;
    counts.set(host, count + 1);
    selected.push(candidate);
    if (selected.length >= limit) break;
  }
  return selected;
}

function classifyFinalUrlType(url, html) {
  const lowerUrl = String(url || "").toLowerCase();
  const lowerHtml = String(html || "").slice(0, 250000).toLowerCase();
  if (!url) return "unknown";
  if (/captcha|access denied|verify you are human|cf-chl|bot detection/.test(lowerHtml)) return "blocked";
  if (/\/products?\//.test(lowerUrl) || /\/shop\//.test(lowerUrl)) return "product";
  if (
    /add to cart|add-to-cart|sold out|out of stock|sku|product-detail|product__/.test(lowerHtml) &&
    /price|size|color|variant/.test(lowerHtml)
  ) {
    return "product";
  }
  if (/\/collections?\//.test(lowerUrl) || /\/search/.test(lowerUrl) || /\/account|\/login/.test(lowerUrl)) return "non_product";
  if (/<title>[^<]*(home|homepage|collection|search|login|account)[^<]*<\/title>/.test(lowerHtml)) return "non_product";
  return "unknown";
}

function classifyStatus({ status, finalUrl, originalUrl, html, fetchError, timedOut }) {
  if (timedOut) {
    return {
      source_status: "timeout",
      source_final_url_type: "unknown",
      evidence: "request timed out",
      error: fetchError,
    };
  }
  if (fetchError) {
    return {
      source_status: "unknown",
      source_final_url_type: "unknown",
      evidence: "fetch failed",
      error: fetchError,
    };
  }

  const finalUrlType = classifyFinalUrlType(finalUrl, html);
  const lower = String(html || "").slice(0, 250000).toLowerCase();
  if (status === 404 || /page not found|404 not found|product not found/.test(lower)) {
    return {
      source_status: "page_not_found",
      source_final_url_type: finalUrlType === "product" ? "unknown" : finalUrlType,
      evidence: `http ${status}; page-not-found phrase`,
      error: null,
    };
  }
  if (status === 429) {
    return {
      source_status: "blocked_or_forbidden",
      source_final_url_type: finalUrlType,
      evidence: "http 429; rate limited",
      error: null,
    };
  }
  if (status === 403 || status === 401 || /captcha|access denied|verify you are human|bot detection/.test(lower)) {
    return {
      source_status: "blocked_or_forbidden",
      source_final_url_type: "blocked",
      evidence: `http ${status || "unknown"}; blocked/captcha evidence`,
      error: null,
    };
  }
  if (/out of stock|sold out|currently unavailable/.test(lower)) {
    return {
      source_status: "out_of_stock",
      source_final_url_type: finalUrlType,
      evidence: "out-of-stock phrase",
      error: null,
    };
  }
  if (/no longer available|discontinued|unavailable|removed from our site/.test(lower)) {
    return {
      source_status: "product_unavailable",
      source_final_url_type: finalUrlType,
      evidence: "product-unavailable phrase",
      error: null,
    };
  }

  const redirected = Boolean(finalUrl && originalUrl && finalUrl.replace(/\/+$/, "") !== originalUrl.replace(/\/+$/, ""));
  if (redirected && finalUrlType === "product") {
    return {
      source_status: "redirected_to_product",
      source_final_url_type: finalUrlType,
      evidence: "redirected to product-like page",
      error: null,
    };
  }
  if (redirected && finalUrlType !== "product") {
    return {
      source_status: "redirected_to_non_product",
      source_final_url_type: finalUrlType,
      evidence: "redirected to non-product-like page",
      error: null,
    };
  }
  if (status >= 400) {
    return {
      source_status: "unknown",
      source_final_url_type: finalUrlType,
      evidence: `http ${status}`,
      error: null,
    };
  }
  return {
    source_status: "live",
    source_final_url_type: finalUrlType,
    evidence: finalUrlType === "product" ? "http ok; product-like page" : "http ok; product signals unclear",
    error: null,
  };
}

function parseRobots(robotsText, targetUrl, userAgentValue) {
  const target = new URL(targetUrl);
  const agentNeedles = [
    userAgentValue.toLowerCase().split(/[ /;]/)[0],
    "*",
  ].filter(Boolean);
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
    if (target.pathname.startsWith(pathRule)) {
      rules.push({ type: key, rule: value, length: pathRule.length });
    }
  }

  if (!rules.length) return { disallowed: false, rule: null };
  rules.sort((a, b) => b.length - a.length);
  const winner = rules[0];
  return {
    disallowed: winner.type === "disallow",
    rule: `${winner.type}: ${winner.rule}`,
  };
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
    const robotsUrl = `${origin}/robots.txt`;
    try {
      const response = await fetchWithTimeout(robotsUrl, {
        headers: { "User-Agent": userAgent },
      });
      const text = await response.text();
      robotsCache.set(origin, {
        ok: response.ok,
        status: response.status,
        text: response.ok ? text : "",
        error: response.ok ? null : `robots http ${response.status}`,
      });
    } catch (error) {
      robotsCache.set(origin, {
        ok: false,
        status: null,
        text: "",
        error: error?.name === "AbortError" ? "robots timeout" : String(error?.message || error),
      });
    }
  }
  const robots = robotsCache.get(origin);
  if (!robots.ok) {
    return {
      disallowed: false,
      rule: null,
      error: robots.error,
    };
  }
  return {
    ...parseRobots(robots.text, url, userAgent),
    error: null,
  };
}

async function respectDomainDelay(url) {
  const host = new URL(url).hostname;
  const last = lastDomainFetchAt.get(host) || 0;
  const waitMs = Math.max(0, perDomainDelayMs - (Date.now() - last));
  if (waitMs) await sleep(waitMs);
  lastDomainFetchAt.set(host, Date.now());
}

async function auditOne(candidate) {
  const url = candidate.normalized_product_page_url;
  const base = {
    product_page_id: candidate.id,
    normalized_product_page_url: url,
    source_status_checked_at: new Date().toISOString(),
    source_status_checker_version: CHECKER_VERSION,
    user_agent: userAgent,
  };
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return {
      ...base,
      source_status: "unknown",
      source_http_status: null,
      source_final_url: null,
      source_redirected: false,
      source_final_url_type: "unknown",
      robots_disallowed: false,
      source_status_evidence: "invalid url",
      source_status_error: "invalid url",
    };
  }

  const robots = await robotsDecision(url);
  if (robots.disallowed) {
    return {
      ...base,
      source_status: "robots_disallowed",
      source_http_status: null,
      source_final_url: null,
      source_redirected: false,
      source_final_url_type: "unknown",
      robots_disallowed: true,
      source_status_evidence: robots.rule,
      source_status_error: robots.error,
    };
  }

  await respectDomainDelay(url);
  try {
    const response = await fetchWithTimeout(url, {
      headers: {
        "User-Agent": userAgent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      },
    });
    const contentType = response.headers.get("content-type") || "";
    const html = contentType.includes("text/html") ? await response.text() : "";
    const finalUrl = response.url || parsed.href;
    const classified = classifyStatus({
      status: response.status,
      finalUrl,
      originalUrl: parsed.href,
      html,
      fetchError: null,
      timedOut: false,
    });
    return {
      ...base,
      source_status: classified.source_status,
      source_http_status: response.status,
      source_final_url: finalUrl,
      source_redirected: finalUrl.replace(/\/+$/, "") !== parsed.href.replace(/\/+$/, ""),
      source_final_url_type: classified.source_final_url_type,
      robots_disallowed: false,
      source_status_evidence: classified.evidence,
      source_status_error: classified.error || robots.error,
    };
  } catch (error) {
    const timedOut = error?.name === "AbortError";
    const classified = classifyStatus({
      status: null,
      finalUrl: null,
      originalUrl: parsed.href,
      html: "",
      fetchError: String(error?.message || error),
      timedOut,
    });
    return {
      ...base,
      source_status: classified.source_status,
      source_http_status: null,
      source_final_url: null,
      source_redirected: false,
      source_final_url_type: classified.source_final_url_type,
      robots_disallowed: false,
      source_status_evidence: classified.evidence,
      source_status_error: classified.error,
    };
  }
}

function updateSql(results) {
  const updates = results.map((result) => `
update staging.product_pages
set
  source_status = ${sqlString(result.source_status)},
  source_status_checked_at = ${sqlString(result.source_status_checked_at)}::timestamptz,
  source_http_status = ${sqlNumber(result.source_http_status)},
  source_final_url = ${sqlString(result.source_final_url)},
  source_redirected = ${sqlBoolean(result.source_redirected)},
  source_final_url_type = ${sqlString(result.source_final_url_type)},
  source_status_evidence = ${sqlString(result.source_status_evidence)},
  source_status_error = ${sqlString(result.source_status_error)},
  source_status_checker_version = ${sqlString(result.source_status_checker_version)},
  robots_disallowed = ${sqlBoolean(result.robots_disallowed)}
where id = ${sqlString(result.product_page_id)}::uuid;`);
  return `begin;\n${updates.join("\n")}\ncommit;`;
}

function summarize(results) {
  const byStatus = {};
  const robotsByDomain = {};
  for (const result of results) {
    byStatus[result.source_status] = (byStatus[result.source_status] || 0) + 1;
    if (result.robots_disallowed) {
      const host = new URL(result.normalized_product_page_url).hostname;
      robotsByDomain[host] = (robotsByDomain[host] || 0) + 1;
    }
  }
  return { byStatus, robotsByDomain };
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

function statusClass(value) {
  return String(value || "unknown").replace(/[^a-z0-9_-]/gi, "_");
}

function buildReviewHtml(report) {
  const rows = report.results
    .map((result) => `
      <article class="card ${statusClass(result.source_status)}">
        <h2><a href="${htmlEscape(result.normalized_product_page_url)}" target="_blank" rel="noreferrer">${htmlEscape(result.normalized_product_page_url)}</a></h2>
        <div class="pills">
          <span>${htmlEscape(result.source_status)}</span>
          <span>${htmlEscape(result.source_final_url_type)}</span>
          <span>HTTP ${htmlEscape(result.source_http_status ?? "n/a")}</span>
          ${result.robots_disallowed ? "<span>robots disallowed</span>" : ""}
          ${result.source_redirected ? "<span>redirected</span>" : ""}
        </div>
        <dl>
          <dt>Final URL</dt>
          <dd>${result.source_final_url ? `<a href="${htmlEscape(result.source_final_url)}" target="_blank" rel="noreferrer">${htmlEscape(result.source_final_url)}</a>` : "none"}</dd>
          <dt>Evidence</dt>
          <dd>${htmlEscape(result.source_status_evidence)}</dd>
          <dt>Error</dt>
          <dd>${htmlEscape(result.source_status_error || "")}</dd>
          <dt>Checker</dt>
          <dd>${htmlEscape(result.source_status_checker_version)}</dd>
        </dl>
      </article>`)
    .join("\n");
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FWM Dev Product Page Status Audit</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; color: #1f2933; }
    header { margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 16px; }
    .card { border: 1px solid #d9e2ec; border-radius: 8px; padding: 14px; background: #fff; }
    .live, .redirected_to_product { border-color: #2f9e44; }
    .page_not_found, .product_unavailable, .redirected_to_non_product { border-color: #d9480f; }
    .blocked_or_forbidden, .robots_disallowed { border-color: #f08c00; }
    h2 { font-size: 14px; overflow-wrap: anywhere; }
    .pills { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 12px; }
    .pills span { background: #f0f4f8; border-radius: 999px; padding: 4px 8px; font-size: 12px; }
    dl { font-size: 13px; }
    dt { font-weight: 700; margin-top: 8px; }
    dd { margin-left: 0; overflow-wrap: anywhere; color: #334e68; }
  </style>
</head>
<body>
  <header>
    <h1>FWM Dev Product Page Status Audit</h1>
    <p>Generated ${htmlEscape(report.generated_at)}. Mode: ${htmlEscape(report.mode)}. Candidates: ${htmlEscape(report.candidate_count)}.</p>
    <pre>${htmlEscape(JSON.stringify(report.status_counts, null, 2))}</pre>
  </header>
  <main class="grid">${rows}</main>
</body>
</html>
`;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Product-page status audit guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);
  if (apply) {
    throw new Error("Direct status audit apply is disabled. Run a dry-run audit, verify it, then use npm run dev-images:status:promote with the exact report.");
  }

  const targetedIds = await targetedProductPageIds();
  const candidatePool = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, candidateSql(targetedIds)));
  const candidates = selectDomainCappedCandidates(candidatePool);
  const results = [];
  for (const candidate of candidates) {
    results.push(await auditOne(candidate));
  }

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportStem = `dev_product_page_status_audit_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const reportPath = path.join(reportsDir, `${reportStem}.json`);
  const reviewHtmlPath = path.join(reportsDir, `${reportStem}.html`);
  const summary = summarize(results);
  const report = {
    generated_at: generatedAt,
    mode: apply ? "apply" : "dry-run",
    supabase_url: guard.supabaseUrl,
    supabase_project_ref: guard.projectRef,
    checker_version: CHECKER_VERSION,
    user_agent: userAgent,
    limit,
    only_unchecked: onlyUnchecked,
    timeout_ms: timeoutMs,
    per_domain_delay_ms: perDomainDelayMs,
    max_per_domain: maxPerDomain,
    candidate_pool_count: candidatePool.length,
    candidate_count: candidates.length,
    status_counts: summary.byStatus,
    robots_disallowed_by_domain: summary.robotsByDomain,
    review_html_path: reviewHtmlPath,
    results,
  };

  if (apply) {
    requireExplicitWriteFlag();
    await requirePassedVerificationReport("status");
    if (results.length) runPsql(process.env.DEV_DATABASE_URL, updateSql(results));
  }

  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(reviewHtmlPath, buildReviewHtml(report), "utf8");
  console.log(`Wrote product-page status audit report: ${reportPath}`);
  console.log(`Wrote product-page status review HTML: ${reviewHtmlPath}`);
  console.log(`Mode: ${report.mode}`);
  console.log(`Candidates audited: ${report.candidate_count}`);
  console.log(`Status counts: ${JSON.stringify(report.status_counts)}`);
  console.log(`Robots disallowed by domain: ${JSON.stringify(report.robots_disallowed_by_domain)}`);
  if (!apply) console.log("Dry-run only. No Supabase rows were written.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
