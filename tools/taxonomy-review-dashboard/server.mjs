import { createServer } from "node:http";
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../image-review-dashboard/paths.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
} from "../../scripts/lib/dev-supabase-guard.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "../../scripts/lib/postgres-client.mjs";

const __filename = fileURLToPath(import.meta.url);
const toolDir = path.dirname(__filename);
const repoRoot = path.resolve(toolDir, "../..");
const publicDir = path.join(toolDir, "public");
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4174);
const providedPromotionReport = parseArg("promotion-report") || process.env.FWM_TAXONOMY_PROMOTION_REPORT || null;
const catalogCache = new Map();
const cardsCache = new Map();
const CARDS_CACHE_TTL_MS = 5 * 60 * 1000;
const blockedExtractorVersions = new Set([
  "product_page_taxonomy_rules_v3_jumpsuits_primary_repair",
]);

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".svg", "image/svg+xml"],
]);

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data, null, 2);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store, max-age=0",
  });
  res.end(body);
}

function cardsCacheKey(reqUrl = "/") {
  const url = new URL(reqUrl, `http://${host}:${port}`);
  url.searchParams.delete("refresh");
  return url.pathname + (url.search ? url.search : "");
}

function clearCardsCache() {
  cardsCache.clear();
}

function sendError(res, message, status = 500) {
  sendJson(res, { error: message }, status);
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
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
      [
        ...connection.args,
        "--set",
        "ON_ERROR_STOP=1",
        "--tuples-only",
        "--no-align",
        "--command",
        sql,
      ],
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

function reportPathFromRequest(reqUrl) {
  const url = new URL(reqUrl, `http://${host}:${port}`);
  return url.searchParams.get("promotionReport");
}

function taxonomyReportsDir() {
  return path.join(fwmDataDir(repoRoot), "_reports");
}

function taxonomyDecisionsDir() {
  return path.join(taxonomyReportsDir(), "taxonomy-review-decisions");
}

async function loadDecidedProductPageIds() {
  const decisionsDir = taxonomyDecisionsDir();
  if (!existsSync(decisionsDir)) return new Set();
  const files = await readdir(decisionsDir);
  const decided = new Set();
  for (const file of files) {
    if (!/^dev_taxonomy_review_decisions_\d{8}T\d{6}Z\.json$/.test(file)) continue;
    const report = JSON.parse(await readFile(path.join(decisionsDir, file), "utf8"));
    if (report.review_dashboard_version !== "taxonomy_review_dashboard_v1") continue;
    for (const decision of report.decisions || []) {
      if (decision.product_page_id) decided.add(decision.product_page_id);
    }
  }
  return decided;
}

function pendingPlannedUpdates(report, decidedIds) {
  return (report.planned_updates || []).filter((row) => !decidedIds.has(row.product_page_id));
}

function isStaleJumpsuitPrimaryRow(row) {
  const categoryId = row?.category?.mother_category_id || row?.category?.motherCategoryId || "";
  const itemTags = Array.isArray(row?.item_tags) ? row.item_tags : [];
  return ["dresses", "jumpsuit"].includes(categoryId) && itemTags.some((tag) => ["coverall", "jumpsuit"].includes(tag?.clothing_type_id));
}

function isUnavailableProductPage(row) {
  return new Set(["page_not_found", "product_unavailable", "redirected_to_non_product"]).has(row?.source_status?.source_status);
}

async function readPromotionReport(reportPath) {
  const report = JSON.parse(await readFile(reportPath, "utf8"));
  if (report.mode !== "dry-run" || !Array.isArray(report.planned_updates)) {
    throw new Error(`Expected taxonomy promotion dry-run report, got ${reportPath}`);
  }
  if (report.supabase_project_ref !== "gosqgqpftqlawvnyelkt") {
    throw new Error(`Promotion report does not point to dev Supabase: ${reportPath}`);
  }
  const plannedExtractorVersions = new Set(
    report.planned_updates
      .map((row) => row.extractor_version)
      .filter(Boolean),
  );
  const blockedPlannedVersion = Array.from(plannedExtractorVersions)
    .find((version) => blockedExtractorVersions.has(version));
  if (blockedPlannedVersion) {
    throw new Error(`Promotion report uses blocked taxonomy extractor version ${blockedPlannedVersion}: ${reportPath}`);
  }
  if (report.taxonomy_report_path) {
    const taxonomyReport = JSON.parse(await readFile(report.taxonomy_report_path, "utf8"));
    if (blockedExtractorVersions.has(taxonomyReport.extractor_version)) {
      throw new Error(`Promotion report points to blocked taxonomy extractor version ${taxonomyReport.extractor_version}: ${reportPath}`);
    }
  }
  return report;
}

async function assertAllowedTaxonomyReportPaths(reportPaths, contextLabel) {
  const uniquePaths = Array.from(new Set(reportPaths.filter(Boolean)));
  for (const reportPath of uniquePaths) {
    const taxonomyReport = JSON.parse(await readFile(reportPath, "utf8"));
    if (blockedExtractorVersions.has(taxonomyReport.extractor_version)) {
      throw new Error(`${contextLabel} references blocked taxonomy extractor version ${taxonomyReport.extractor_version}: ${reportPath}`);
    }
  }
}

async function latestPromotionReportPath(decidedIds) {
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  const files = await readdir(reportsDir);
  const candidates = files
    .filter((file) => /^dev_taxonomy_promotion_\d{8}T\d{6}(?:\d{3})?Z\.json$/.test(file))
    .map((file) => path.join(reportsDir, file));
  if (!candidates.length) throw new Error(`No taxonomy promotion reports found in ${reportsDir}`);
  const withStats = await Promise.all(candidates.map(async (file) => ({ file, mtimeMs: (await stat(file)).mtimeMs })));
  withStats.sort((a, b) => b.mtimeMs - a.mtimeMs);
  for (const { file } of withStats) {
    try {
      const report = await readPromotionReport(file);
      if (pendingPlannedUpdates(report, decidedIds).length) return file;
    } catch {
      // Ignore non-dry-run or malformed promotion artifacts when selecting the next pending packet.
    }
  }
  throw new Error(`No pending taxonomy promotion reports found in ${reportsDir}`);
}

async function loadPromotionReport(reqUrl = "/") {
  const decidedIds = await loadDecidedProductPageIds();
  const requested = reportPathFromRequest(reqUrl);
  const defaultReport = requested || providedPromotionReport;
  if (defaultReport) {
    const reportPath = path.resolve(defaultReport);
    const report = await readPromotionReport(reportPath);
    if (requested || pendingPlannedUpdates(report, decidedIds).length) {
      return { reportPath, report, decidedIds };
    }
  }
  const reportPath = path.resolve(await latestPromotionReportPath(decidedIds));
  const report = await readPromotionReport(reportPath);
  return { reportPath, report, decidedIds };
}

async function loadPromotionReports(reqUrl = "/") {
  const decidedIds = await loadDecidedProductPageIds();
  const requested = reportPathFromRequest(reqUrl);
  const defaultReport = requested || providedPromotionReport;
  if (defaultReport) {
    const reportPath = path.resolve(defaultReport);
    const report = await readPromotionReport(reportPath);
    return { reportEntries: [{ reportPath, report }], decidedIds };
  }

  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  const files = await readdir(reportsDir);
  const candidates = files
    .filter((file) => /^dev_taxonomy_promotion_\d{8}T\d{6}(?:\d{3})?Z\.json$/.test(file))
    .map((file) => path.join(reportsDir, file));
  const withStats = await Promise.all(candidates.map(async (file) => ({ file, mtimeMs: (await stat(file)).mtimeMs })));
  withStats.sort((a, b) => b.mtimeMs - a.mtimeMs);

  const reportEntries = [];
  for (const { file } of withStats) {
    try {
      const report = await readPromotionReport(file);
      if (pendingPlannedUpdates(report, decidedIds).length) reportEntries.push({ reportPath: file, report });
    } catch {
      // Ignore non-dry-run, partial, or malformed promotion artifacts in the all-pending queue.
    }
  }
  if (!reportEntries.length) throw new Error(`No pending taxonomy promotion reports found in ${reportsDir}`);
  return { reportEntries, decidedIds };
}

async function loadReviewImages(productPageIds) {
  if (!productPageIds.length) return new Map();
  const ids = productPageIds.map(sqlString).join(",");
  const sql = `
select coalesce(jsonb_agg(row_to_json(row_data)), '[]'::jsonb)
from (
  select
    i.product_page_id::text as product_page_id,
    i.id::text as image_id,
    i.original_url_display as review_image_url,
    i.product_page_url_display,
    i.monetized_product_url_display,
    i.review_row_key,
    i.source_file,
    i.source_row_number,
    i.source_site_display,
    i.size_display,
    i.height_in_display,
    i.weight_display_display,
    i.reviewer_name_raw,
    i.user_comment
  from public.images i
  where i.product_page_id::text in (${ids})
    and i.original_url_display is not null
  order by
    i.product_page_id,
    (i.review_row_key like 'nonamazon::%::%-model%'),
    (i.review_row_key like 'baseline:%'),
    (i.user_comment is null),
    i.updated_at desc nulls last
) row_data;`;
  const rows = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, sql));
  const byProductPage = new Map();
  for (const row of rows) {
    if (!byProductPage.has(row.product_page_id)) byProductPage.set(row.product_page_id, []);
    byProductPage.get(row.product_page_id).push(row);
  }
  return byProductPage;
}

async function loadImageRowCounts(productPageIds) {
  if (!productPageIds.length) return new Map();
  const ids = productPageIds.map(sqlString).join(",");
  const sql = `
select coalesce(jsonb_agg(row_to_json(row_data)), '[]'::jsonb)
from (
  select
    pp.id::text as product_page_id,
    count(i.*)::int as image_row_count
  from staging.product_pages pp
  left join public.images i on i.product_page_id = pp.id
  where pp.id::text in (${ids})
  group by pp.id
) row_data;`;
  const rows = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, sql));
  return new Map(rows.map((row) => [row.product_page_id, Number(row.image_row_count || 0)]));
}

async function loadStoredCatalogs(productPageIds) {
  if (!productPageIds.length) return new Map();
  const columnSql = `
select coalesce(jsonb_agg(column_name), '[]'::jsonb)
from information_schema.columns
where table_schema = 'staging'
  and table_name = 'product_pages'
  and column_name in (
    'catalog_image_url',
    'catalog_image_urls',
    'catalog_image_source',
    'catalog_image_fetched_at',
    'catalog_image_fetch_status',
    'catalog_image_fetch_error'
  );`;
  const columns = new Set(parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, columnSql)));
  if (!columns.has("catalog_image_url")) return new Map();
  const columnExpr = (column, fallback) => columns.has(column) ? `pp.${column}` : fallback;
  const ids = productPageIds.map(sqlString).join(",");
  const sql = `
select coalesce(jsonb_agg(row_to_json(row_data)), '[]'::jsonb)
from (
  select
    pp.id::text as product_page_id,
    ${columnExpr("catalog_image_url", "null::text")} as catalog_image_url,
    ${columnExpr("catalog_image_urls", "'{}'::text[]")} as catalog_image_urls,
    ${columnExpr("catalog_image_source", "null::text")} as catalog_image_source,
    ${columnExpr("catalog_image_fetched_at", "null::timestamptz")} as catalog_image_fetched_at,
    ${columnExpr("catalog_image_fetch_status", "null::text")} as catalog_image_fetch_status,
    ${columnExpr("catalog_image_fetch_error", "null::text")} as catalog_image_fetch_error,
    pp.product_title_raw as fetched_title
  from staging.product_pages pp
  where pp.id::text in (${ids})
) row_data;`;
  const rows = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, sql));
  return new Map(rows.map((row) => [row.product_page_id, row]));
}

async function loadProductPageStatuses(productPageIds) {
  if (!productPageIds.length) return new Map();
  const ids = productPageIds.map(sqlString).join(",");
  const sql = `
select coalesce(jsonb_agg(row_to_json(row_data)), '[]'::jsonb)
from (
  select
    pp.id::text as product_page_id,
    pp.source_status,
    pp.source_http_status,
    pp.source_final_url,
    pp.source_redirected,
    pp.source_final_url_type,
    pp.source_status_evidence,
    pp.source_status_checked_at,
    pp.source_status_checker_version
  from staging.product_pages pp
  where pp.id::text in (${ids})
) row_data;`;
  const rows = parseJsonPsql(runPsql(process.env.DEV_DATABASE_URL, sql));
  return new Map(rows.map((row) => [row.product_page_id, row]));
}

function extractJsonLdImages(html, baseUrl) {
  const images = [];
  const scriptPattern = /<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let match;
  while ((match = scriptPattern.exec(html))) {
    try {
      const parsed = JSON.parse(match[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&"));
      const nodes = Array.isArray(parsed) ? parsed : [parsed];
      for (const node of nodes.flatMap((item) => item?.["@graph"] || item)) {
        collectImageValues(node?.image, baseUrl, images);
        collectImageValues(node?.offers?.image, baseUrl, images);
      }
    } catch {
      // Merchant JSON-LD is often malformed; meta tags below are the fallback.
    }
  }
  return images;
}

function collectImageValues(value, baseUrl, images) {
  if (!value) return;
  if (typeof value === "string") {
    images.push(resolveUrl(value, baseUrl));
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectImageValues(item, baseUrl, images);
    return;
  }
  collectImageValues(value.url || value.contentUrl, baseUrl, images);
}

function resolveUrl(value, baseUrl) {
  try {
    return new URL(String(value).trim(), baseUrl).href;
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

function metaContent(html, property) {
  const escaped = property.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`<meta[^>]+(?:property|name)=["']${escaped}["'][^>]+content=["']([^"']+)["'][^>]*>`, "i");
  return html.match(pattern)?.[1] || "";
}

function htmlTitle(html) {
  return html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1]?.replace(/\s+/g, " ").trim() || "";
}

function redirectedToHomepage(originalUrl, finalUrl) {
  try {
    const original = new URL(originalUrl);
    const final = new URL(finalUrl || originalUrl);
    return (
      final.origin === original.origin.replace(/^http:\/\//, "https://").replace(/^https:\/\/(?!www\.)/, "https://www.") ||
      final.hostname.replace(/^www\./, "") === original.hostname.replace(/^www\./, "")
    ) && final.pathname.replace(/\/+$/, "") === "" && original.pathname.replace(/\/+$/, "") !== "";
  } catch {
    return false;
  }
}

async function shopifyProductPreview(productUrl) {
  try {
    const parsed = new URL(productUrl);
    const productJsonUrl = `${parsed.origin}${parsed.pathname.replace(/\/+$/, "")}.js`;
    const response = await fetch(productJsonUrl, {
      redirect: "follow",
      signal: AbortSignal.timeout(7000),
      headers: {
        "user-agent": "FWMDevTaxonomyReviewDashboard/0.1 (+https://friendswithmeasurements.com)",
        accept: "application/json,text/javascript,*/*",
      },
    });
    if (!response.ok) return null;
    const product = await response.json();
    const catalogImageUrls = uniqueLikelyImageUrls(
      [product.featured_image, product.image, ...(Array.isArray(product.images) ? product.images : [])],
      productJsonUrl,
    );
    if (!catalogImageUrls.length && !product.title) return null;
    return {
      catalog_image_url: catalogImageUrls[0] || "",
      catalog_image_urls: catalogImageUrls,
      catalog_image_source: catalogImageUrls.length ? "shopify_product_json" : "",
      fetched_title: product.title || "",
    };
  } catch {
    return null;
  }
}

async function catalogPreview(url) {
  if (!url) return { catalog_image_url: "", catalog_image_urls: [], catalog_image_source: "", fetched_title: "" };
  if (catalogCache.has(url)) return catalogCache.get(url);
  const promise = (async () => {
    let pageTitle = "";
    try {
      const response = await fetch(url, {
        redirect: "follow",
        signal: AbortSignal.timeout(7000),
        headers: {
          "user-agent": "FWMDevTaxonomyReviewDashboard/0.1 (+https://friendswithmeasurements.com)",
          accept: "text/html,application/xhtml+xml",
        },
      });
      if (response.status >= 400 || redirectedToHomepage(url, response.url)) {
        return {
          catalog_image_url: "",
          catalog_image_urls: [],
          catalog_image_source: "",
          fetched_title: "",
          catalog_fetch_status: response.status >= 400 ? `http_status_${response.status}` : "redirected_to_homepage",
        };
      }
      const html = await response.text();
      pageTitle = htmlTitle(html);
      const jsonLdImages = uniqueLikelyImageUrls(extractJsonLdImages(html, response.url), response.url);
      const metaImages = uniqueLikelyImageUrls([metaContent(html, "og:image"), metaContent(html, "twitter:image")], response.url);
      const shopifyPreview = jsonLdImages.length || metaImages.length ? null : await shopifyProductPreview(url);
      const catalogImageUrls = jsonLdImages.length ? jsonLdImages : metaImages.length ? metaImages : shopifyPreview?.catalog_image_urls || [];
      return {
        catalog_image_url: catalogImageUrls[0] || "",
        catalog_image_urls: catalogImageUrls,
        catalog_image_source: jsonLdImages.length ? "json_ld" : metaImages.length ? "meta" : shopifyPreview?.catalog_image_source || "",
        fetched_title: pageTitle && pageTitle !== "Something went wrong" ? pageTitle : shopifyPreview?.fetched_title || pageTitle,
      };
    } catch (error) {
      const shopifyPreview = await shopifyProductPreview(url);
      if (shopifyPreview) return shopifyPreview;
      return {
        catalog_image_url: "",
        catalog_image_urls: [],
        catalog_image_source: "",
        fetched_title: pageTitle,
        catalog_fetch_error: error.message || String(error),
      };
    }
  })();
  catalogCache.set(url, promise);
  return promise;
}

function normalizeComparableUrl(value) {
  try {
    const url = new URL(String(value || ""));
    url.search = "";
    return url.href.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/+$/, "").toLowerCase();
  } catch {
    return String(value || "").trim().toLowerCase();
  }
}

function isCatalogLikeImage(row, catalog) {
  const key = String(row?.review_row_key || "").toLowerCase();
  if (/^nonamazon::.*::.*-model/.test(key)) return true;
  const reviewUrl = normalizeComparableUrl(row?.review_image_url);
  const catalogUrl = normalizeComparableUrl(catalog?.catalog_image_url);
  return Boolean(reviewUrl && catalogUrl && reviewUrl === catalogUrl);
}

function reviewImageRejectionReason(row, catalog) {
  if (isCatalogLikeImage(row, catalog)) return "catalog_like_image";
  return "";
}

function chooseReviewImage(rows, catalog) {
  const candidates = Array.isArray(rows) ? rows : [];
  return candidates.find((row) => !reviewImageRejectionReason(row, catalog)) || null;
}

function reviewImageHiddenReasons(rows, catalog) {
  const candidates = Array.isArray(rows) ? rows : [];
  return Array.from(new Set(candidates.map((row) => reviewImageRejectionReason(row, catalog)).filter(Boolean)));
}

function matchingAuditResult(taxonomyReport, productPageId) {
  return (taxonomyReport.results || []).find((row) => row.product_page_id === productPageId) || null;
}

async function buildCards(reqUrl) {
  const { reportEntries, decidedIds } = await loadPromotionReports(reqUrl);
  const taxonomyReports = new Map();
  const seenProductPageIds = new Set();
  const pendingRows = [];
  for (const { reportPath, report } of reportEntries) {
    if (!taxonomyReports.has(report.taxonomy_report_path)) {
      taxonomyReports.set(report.taxonomy_report_path, JSON.parse(await readFile(report.taxonomy_report_path, "utf8")));
    }
    for (const row of pendingPlannedUpdates(report, decidedIds)) {
      if (seenProductPageIds.has(row.product_page_id)) continue;
      seenProductPageIds.add(row.product_page_id);
      pendingRows.push({
        ...row,
        promotion_report_path: reportPath,
        taxonomy_report_path: report.taxonomy_report_path,
      });
    }
  }
  const productPageIds = pendingRows.map((row) => row.product_page_id);
  const reviewImages = await loadReviewImages(productPageIds);
  const imageRowCounts = await loadImageRowCounts(productPageIds);
  const storedCatalogs = await loadStoredCatalogs(productPageIds);
  const sourceStatuses = await loadProductPageStatuses(productPageIds);
  const allCards = pendingRows.map((row) => {
    const taxonomyReport = taxonomyReports.get(row.taxonomy_report_path);
    const audit = matchingAuditResult(taxonomyReport, row.product_page_id);
    const storedCatalog = storedCatalogs.get(row.product_page_id);
    const auditCatalog = audit?.catalog || {};
    const catalog = storedCatalog?.catalog_image_url
      ? {
          catalog_image_url: storedCatalog.catalog_image_url,
          catalog_image_urls: storedCatalog.catalog_image_urls || (storedCatalog.catalog_image_url ? [storedCatalog.catalog_image_url] : []),
          catalog_image_source: storedCatalog.catalog_image_source || "staging.product_pages",
          catalog_image_fetched_at: storedCatalog.catalog_image_fetched_at || null,
          catalog_image_fetch_status: storedCatalog.catalog_image_fetch_status || "",
          catalog_image_fetch_error: storedCatalog.catalog_image_fetch_error || "",
          fetched_title: storedCatalog.fetched_title || "",
        }
      : auditCatalog.catalog_image_url
        ? {
            ...auditCatalog,
            catalog_image_urls: auditCatalog.catalog_image_urls || [auditCatalog.catalog_image_url],
            fetched_title: "",
          }
        : { catalog_image_url: "", catalog_image_urls: [], catalog_image_source: "lazy", fetched_title: "" };
    const reviewImageRows = reviewImages.get(row.product_page_id) || [];
    const reviewImage = chooseReviewImage(reviewImageRows, catalog);
    const reviewImageHiddenReasonList = reviewImageHiddenReasons(reviewImageRows, catalog);
    return {
      ...row,
      source_status: sourceStatuses.get(row.product_page_id) || null,
      audit,
      product_title:
        audit?.workbook_hints?.product_title_raw ||
        audit?.extracted_fields_preview?.title ||
        "",
      catalog,
      review_image: reviewImage,
      review_image_status: reviewImage ? "found" : "no_customer_review_image_found",
      review_image_hidden_reasons: reviewImageHiddenReasonList,
    };
  });
  const staleJumpsuitPrimaryCards = allCards.filter(isStaleJumpsuitPrimaryRow);
  const unavailableProductPageCards = allCards.filter(isUnavailableProductPage);
  const missingImageRowCards = allCards.filter((card) => !imageRowCounts.get(card.product_page_id));
  const missingPrimaryCategoryCards = allCards.filter((card) => !card.category);
  const cards = allCards.filter((card) => card.category && !isStaleJumpsuitPrimaryRow(card) && !isUnavailableProductPage(card) && imageRowCounts.get(card.product_page_id));
  return {
    promotion_report_path: reportEntries.length === 1 ? reportEntries[0].reportPath : "all pending taxonomy promotion reports",
    promotion_report_paths: reportEntries.map(({ reportPath }) => reportPath),
    taxonomy_report_path: reportEntries.length === 1 ? reportEntries[0].report.taxonomy_report_path : "multiple taxonomy audit reports",
    taxonomy_report_paths: Array.from(new Set(reportEntries.map(({ report }) => report.taxonomy_report_path))),
    generated_at: new Date().toISOString(),
    summary: {
      planned_update_count: reportEntries.reduce((sum, { report }) => sum + (report.planned_updates || []).length, 0),
      pending_planned_update_count: pendingRows.length,
      stale_jumpsuit_primary_hidden_count: staleJumpsuitPrimaryCards.length,
      stale_jumpsuit_primary_product_page_ids: staleJumpsuitPrimaryCards.map((card) => card.product_page_id),
      unavailable_product_page_hidden_count: unavailableProductPageCards.length,
      unavailable_product_page_ids: unavailableProductPageCards.map((card) => card.product_page_id),
      missing_image_row_hidden_count: missingImageRowCards.length,
      missing_image_row_product_page_ids: missingImageRowCards.map((card) => card.product_page_id),
      missing_primary_category_count: missingPrimaryCategoryCards.length,
      missing_primary_category_product_page_ids: missingPrimaryCategoryCards.map((card) => card.product_page_id),
      already_decided_count: decidedIds.size,
      reviewable_card_count: cards.length,
      missing_customer_review_image_count: cards.filter((card) => !card.review_image).length,
      source_promotion_report_count: reportEntries.length,
    },
    cards,
  };
}

async function cachedBuildCards(reqUrl) {
  const url = new URL(reqUrl || "/", `http://${host}:${port}`);
  const key = cardsCacheKey(reqUrl || "/");
  const cached = cardsCache.get(key);
  if (!url.searchParams.has("refresh") && cached && Date.now() - cached.createdAt < CARDS_CACHE_TTL_MS) {
    return { ...cached.packet, cache: { hit: true, cached_at: cached.createdAt } };
  }
  const packet = await buildCards(reqUrl);
  cardsCache.set(key, { createdAt: Date.now(), packet });
  return { ...packet, cache: { hit: false, cached_at: Date.now() } };
}

function packetFromDecisionContext(body) {
  const contextRows = Array.isArray(body.decision_context) ? body.decision_context : [];
  const cards = contextRows
    .filter((row) =>
      row &&
      typeof row.product_page_id === "string" &&
      typeof row.promotion_report_path === "string" &&
      typeof row.taxonomy_report_path === "string"
    )
    .map((row) => ({
      product_page_id: row.product_page_id,
      promotion_report_path: row.promotion_report_path,
      taxonomy_report_path: row.taxonomy_report_path,
    }));
  if (!cards.length) return null;
  return {
    promotion_report_path: typeof body.promotion_report_path === "string" ? body.promotion_report_path : "",
    promotion_report_paths: Array.isArray(body.promotion_report_paths) ? body.promotion_report_paths.filter((value) => typeof value === "string") : [],
    taxonomy_report_path: typeof body.taxonomy_report_path === "string" ? body.taxonomy_report_path : "",
    taxonomy_report_paths: Array.isArray(body.taxonomy_report_paths) ? body.taxonomy_report_paths.filter((value) => typeof value === "string") : [],
    summary: body.summary && typeof body.summary === "object" && !Array.isArray(body.summary) ? body.summary : {},
    cards,
  };
}

async function saveDecisions(req) {
  const body = await readJsonBody(req);
  const promotionReportPaths = Array.isArray(body.promotion_report_paths) ? body.promotion_report_paths : [];
  const isSingleReportSave = promotionReportPaths.length === 1 && body.promotion_report_path === promotionReportPaths[0];
  const packet = packetFromDecisionContext(body) || await buildCards(
    isSingleReportSave
      ? `/?promotionReport=${encodeURIComponent(body.promotion_report_path)}`
      : "/",
  );
  await assertAllowedTaxonomyReportPaths([
    packet.taxonomy_report_path === "multiple taxonomy audit reports" ? "" : packet.taxonomy_report_path,
    ...(packet.taxonomy_report_paths || []),
    ...packet.cards.map((card) => card.taxonomy_report_path),
  ], "Taxonomy review decision save");
  const decisions = Array.isArray(body.decisions) ? body.decisions : [];
  const cardsByProductPageId = new Map(packet.cards.map((row) => [row.product_page_id, row]));
  const plannedIds = new Set(cardsByProductPageId.keys());
  const cleaned = decisions
    .filter((decision) => plannedIds.has(decision.product_page_id))
    .map((decision) => {
      const card = cardsByProductPageId.get(decision.product_page_id);
      return {
        product_page_id: decision.product_page_id,
        promotion_report_path: card?.promotion_report_path || null,
        taxonomy_report_path: card?.taxonomy_report_path || null,
        decision: decision.decision === "approved"
          ? "approved"
          : decision.decision === "rejected"
            ? "rejected"
            : decision.decision === "not_product"
              ? "not_product"
              : "needs_review",
        reviewer_note: String(decision.reviewer_note || "").trim(),
        decided_at: decision.decided_at || new Date().toISOString(),
      };
    });
  const approved = cleaned.filter((decision) => decision.decision === "approved");
  const generatedAt = new Date().toISOString();
  const decisionsDir = path.join(fwmDataDir(repoRoot), "_reports", "taxonomy-review-decisions");
  await mkdir(decisionsDir, { recursive: true });
  const outputPath = path.join(
    decisionsDir,
    `dev_taxonomy_review_decisions_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`,
  );
  const payload = {
    generated_at: generatedAt,
    review_dashboard_version: "taxonomy_review_dashboard_v1",
    supabase_url: "https://gosqgqpftqlawvnyelkt.supabase.co",
    supabase_project_ref: "gosqgqpftqlawvnyelkt",
    promotion_report_path: packet.promotion_report_path,
    promotion_report_paths: packet.promotion_report_paths || [],
    taxonomy_report_path: packet.taxonomy_report_path,
    taxonomy_report_paths: packet.taxonomy_report_paths || [],
    planned_update_count: packet.summary?.planned_update_count || packet.cards.length,
    decision_count: cleaned.length,
    approved_count: approved.length,
    rejected_count: cleaned.filter((decision) => decision.decision === "rejected").length,
    not_product_count: cleaned.filter((decision) => decision.decision === "not_product").length,
    needs_review_count: cleaned.filter((decision) => decision.decision === "needs_review").length,
    approved_product_page_ids: approved.map((decision) => decision.product_page_id),
    decisions: cleaned,
  };
  await writeFile(outputPath, JSON.stringify(payload, null, 2) + "\n", "utf8");
  clearCardsCache();
  return { output_path: outputPath, ...payload };
}

function resolveStaticPath(urlPath) {
  const cleanPath = decodeURIComponent(urlPath.split("?")[0]);
  const normalized = cleanPath === "/" ? "/index.html" : cleanPath;
  const candidate = path.resolve(publicDir, `.${normalized}`);
  return candidate.startsWith(publicDir) ? candidate : null;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Taxonomy review dashboard guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url || "/", `http://${host}:${port}`);
      if (req.method === "GET" && url.pathname === "/api/cards") {
        sendJson(res, await cachedBuildCards(req.url || "/"));
        return;
      }
      if (req.method === "GET" && url.pathname === "/api/catalog-preview") {
        sendJson(res, await catalogPreview(url.searchParams.get("url") || ""));
        return;
      }
      if (req.method === "POST" && url.pathname === "/api/decisions") {
        sendJson(res, await saveDecisions(req));
        return;
      }
      if (req.method !== "GET") {
        sendError(res, "Method not allowed", 405);
        return;
      }
      const filePath = resolveStaticPath(req.url || "/");
      if (!filePath || !existsSync(filePath) || !(await stat(filePath)).isFile()) {
        sendError(res, "Not found", 404);
        return;
      }
      const ext = path.extname(filePath);
      res.writeHead(200, {
        "Content-Type": contentTypes.get(ext) || "application/octet-stream",
        "Cache-Control": "no-store",
      });
      createReadStream(filePath).pipe(res);
    } catch (error) {
      sendError(res, error.message || String(error), 500);
    }
  });

  server.listen(port, host, () => {
    console.log(`Taxonomy review dashboard running at http://${host}:${port}`);
  });
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
