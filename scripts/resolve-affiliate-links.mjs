#!/usr/bin/env node
/**
 * Resolve the best affiliate link for every row in staging.product_pages and
 * write the result back to the five affiliate_* columns added by migration
 * 20260620000000.
 *
 * Network resolution order:
 *   Amazon Associates  — any amazon.com page; builds ?tag= URL immediately
 *   AWIN               — domain matched in AWIN advertiser CSVs; URL pending
 *                        generation by generate_awin_affiliate_links.py
 *   Sovrn JS SDK       — domain in Sovrn triage CSVs; JS SDK rewrites at
 *                        click time, no pre-generated URL stored
 *   null               — no affiliate program found
 *
 * When both AWIN and Sovrn match, AWIN is primary (pre-generated, better
 * attribution) and Sovrn is stored as fallback.
 *
 * Usage:
 *   node scripts/resolve-affiliate-links.mjs                    # dry-run
 *   node scripts/resolve-affiliate-links.mjs --amazon-only      # Amazon rows only
 *   node scripts/resolve-affiliate-links.mjs --apply            # write to dev DB
 *                                                                 (requires guard)
 *   node scripts/resolve-affiliate-links.mjs --apply \
 *     --backfill-images                                          # also update
 *                                                                 public.images
 */

import { execFileSync, execSync } from "node:child_process";
import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";
import {
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// --- .env loader (fills values not already in environment) ------------------
function loadDotEnv() {
  const envPath = path.join(repoRoot, ".env");
  if (!existsSync(envPath)) return;
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
    if (!m) continue;
    const key = m[1];
    let val = m[2];
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = val;
  }
}

loadDotEnv();

// --- CLI args ---------------------------------------------------------------
const args = process.argv.slice(2);
const apply = args.includes("--apply");
const amazonOnly = args.includes("--amazon-only");
const backfillImages = args.includes("--backfill-images");
const forceRefresh = args.includes("--refresh-working-copy");

// --- paths ------------------------------------------------------------------
const fwmDataDir = process.env.FWM_DATA_DIR;
if (!fwmDataDir) throw new Error("FWM_DATA_DIR is not set in environment or .env");

const workingCopyPath = path.join(
  repoRoot,
  "data-pipelines",
  "products",
  "product_pages_working_copy.ndjson",
);
const awinLeadsDir = path.join(
  fwmDataDir,
  "_reports",
  "measurement_coverage",
  "20260609_human_labeled_approved_only",
  "affiliate_network_leads",
);
const awinAdvertiserCsvs = [
  path.join(awinLeadsDir, "awin_program_review_scrape_join_recommendations.csv"),
  path.join(awinLeadsDir, "awin_all_clothing_advertisers_triaged_2026-06-10.csv"),
];
const sovrnCsvs = [
  path.join(repoRoot, "data-pipelines", "docs", "sovrn_commerce", "sovrn_commerce_scrape_triage_candidates.csv"),
  path.join(repoRoot, "data-pipelines", "docs", "sovrn_commerce", "sovrn_commerce_apparel_triage_tracker.csv"),
];

const AMAZON_TAG = process.env.AMAZON_ASSOCIATES_TAG || "friendswithm-20";

// --- simple CSV parser (header row + field split, no external deps) ---------
function parseSimpleCsv(text) {
  const lines = text.split(/\r?\n/);
  if (!lines.length) return [];
  const headers = splitCsvRow(lines[0]);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const values = splitCsvRow(line);
    const row = {};
    for (let j = 0; j < headers.length; j++) {
      row[headers[j]] = values[j] ?? "";
    }
    rows.push(row);
  }
  return rows;
}

function splitCsvRow(line) {
  const fields = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      fields.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

// --- domain helpers ---------------------------------------------------------
function domainFromUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw.includes("://") ? raw : `https://${raw}`);
    return url.hostname.toLowerCase().replace(/^www\./, "").replace(/^m\./, "");
  } catch {
    return "";
  }
}

function* domainVariants(domain) {
  let current = domain.toLowerCase().replace(/^\.+|\.+$/g, "");
  while (current) {
    yield current;
    if (!current.includes(".")) break;
    current = current.slice(current.indexOf(".") + 1);
  }
}

// --- AWIN advertiser loader -------------------------------------------------
function loadAwinAdvertisers(csvPaths) {
  const map = new Map(); // normalized_domain -> { advertiserId, programmeName, epc }
  for (const csvPath of csvPaths) {
    if (!existsSync(csvPath)) continue;
    const rows = parseSimpleCsv(readFileSync(csvPath, "utf8"));
    for (const row of rows) {
      const advertiserId = String(row.advertiserId || "").trim();
      const rawDomain =
        String(row.normalized_domain || row.displayUrl || "").trim();
      const domain = domainFromUrl(rawDomain || rawDomain);
      if (!advertiserId || !domain) continue;
      if (!map.has(domain)) {
        const epcRaw = parseFloat(String(row.epc || "").replace(/[^0-9.]/g, ""));
        map.set(domain, {
          advertiserId,
          programmeName: String(row.programmeName || "").trim(),
          epc: isNaN(epcRaw) ? null : epcRaw,
        });
      }
    }
  }
  return map;
}

// --- Sovrn merchant loader --------------------------------------------------
function loadSovrnMerchants(csvPaths) {
  const map = new Map(); // normalized_domain -> { payout_priority_rank, pricing, epc }
  for (const csvPath of csvPaths) {
    if (!existsSync(csvPath)) continue;
    const rows = parseSimpleCsv(readFileSync(csvPath, "utf8"));
    for (const row of rows) {
      const rawDomains = String(
        row.primary_domain || row.primary_domains || "",
      ).trim();
      const epcRaw = parseFloat(
        String(row.estimated_commission_per_click || "")
          .replace(/[$,]/g, "")
          .trim(),
      );
      const rank = parseInt(String(row.payout_priority_rank || ""), 10);
      for (const part of rawDomains.split(/[;,|]/)) {
        const domain = domainFromUrl(part.trim());
        if (!domain) continue;
        const existing = map.get(domain);
        const newRank = isNaN(rank) ? 999999 : rank;
        if (!existing || newRank < (existing.rank ?? 999999)) {
          map.set(domain, {
            rank: newRank,
            pricing: String(row.pricing || "").trim().toUpperCase(),
            epc: isNaN(epcRaw) ? null : epcRaw,
          });
        }
      }
    }
  }
  return map;
}

// --- Amazon ASIN extraction -------------------------------------------------
const ASIN_RE = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})/;

function extractAsin(url) {
  const m = ASIN_RE.exec(String(url || ""));
  return m ? m[1] : null;
}

function buildAmazonAffiliateUrl(asin) {
  return `https://www.amazon.com/dp/${asin}?tag=${AMAZON_TAG}`;
}

// --- Network selection ------------------------------------------------------
function selectNetwork(domain, awinMap, sovrnMap) {
  const isAmazon = /\bamazon\./i.test(domain);
  if (isAmazon) return { primary: "amazon_associates", fallback: null };

  let awinEntry = null;
  for (const variant of domainVariants(domain)) {
    if (awinMap.has(variant)) {
      awinEntry = awinMap.get(variant);
      break;
    }
  }

  let sovrnEntry = null;
  for (const variant of domainVariants(domain)) {
    if (sovrnMap.has(variant)) {
      sovrnEntry = sovrnMap.get(variant);
      break;
    }
  }

  const awinEpc = awinEntry?.epc ?? null;
  const sovrnEpc = sovrnEntry?.epc ?? null;

  if (awinEntry && !sovrnEntry) return { primary: "awin", fallback: null, awinEntry };
  if (sovrnEntry && !awinEntry) return { primary: "sovrn_js", fallback: null, sovrnEntry };
  if (awinEntry && sovrnEntry) {
    // Both available: prefer AWIN (pre-generated, better attribution), Sovrn as fallback.
    // Exception: if Sovrn EPC is clearly higher and AWIN EPC is known, prefer Sovrn primary.
    if (sovrnEpc !== null && awinEpc !== null && sovrnEpc > awinEpc) {
      return { primary: "sovrn_js", fallback: "awin", sovrnEntry, awinEntry };
    }
    return { primary: "awin", fallback: "sovrn_js", awinEntry, sovrnEntry };
  }
  return { primary: null, fallback: null };
}

// --- Resolution -------------------------------------------------------------
function resolveRow(row, awinMap, sovrnMap) {
  const url = String(row.normalized_product_page_url || "");
  const domain = domainFromUrl(url);
  const selection = selectNetwork(domain, awinMap, sovrnMap);

  let affiliateNetwork = null;
  let affiliateUrl = null;
  let affiliateUrlFallback = null;
  let affiliateNetworkFallback = null;

  if (selection.primary === "amazon_associates") {
    const asin = extractAsin(url);
    if (asin) {
      affiliateNetwork = "amazon_associates";
      affiliateUrl = buildAmazonAffiliateUrl(asin);
      affiliateUrlFallback = url;
    }
  } else if (selection.primary === "awin") {
    affiliateNetwork = "awin";
    affiliateUrl = null; // generated separately by generate_awin_affiliate_links.py
    if (selection.fallback === "sovrn_js") {
      affiliateNetworkFallback = "sovrn_js";
    }
  } else if (selection.primary === "sovrn_js") {
    affiliateNetwork = "sovrn_js";
    affiliateUrl = null; // JS SDK rewrites at click time
    if (selection.fallback === "awin") {
      affiliateNetworkFallback = "awin";
    }
  }

  return {
    id: row.id,
    normalized_product_page_url: url,
    affiliate_network: affiliateNetwork,
    affiliate_url: affiliateUrl,
    affiliate_url_fallback: affiliateUrlFallback,
    affiliate_network_fallback: affiliateNetworkFallback,
  };
}

// --- SQL helpers ------------------------------------------------------------
function sqlLiteral(value) {
  if (value === null || value === undefined) return "null";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function buildUpdateSql(resolved) {
  const statements = resolved.map(
    (r) => `update staging.product_pages set
  affiliate_network          = ${sqlLiteral(r.affiliate_network)},
  affiliate_url              = ${sqlLiteral(r.affiliate_url)},
  affiliate_url_fallback     = ${sqlLiteral(r.affiliate_url_fallback)},
  affiliate_network_fallback = ${sqlLiteral(r.affiliate_network_fallback)},
  affiliate_resolved_at      = now()
where id = ${sqlLiteral(r.id)}::uuid;`,
  );
  return `begin;\n${statements.join("\n")}\ncommit;`;
}

function buildImagesBackfillSql(amazonResolved) {
  // Update public.images.monetized_product_url_display for Amazon rows via
  // JOIN on product_page_url_display. Only sets rows that are currently null
  // or empty so we don't overwrite existing AWIN/Sovrn tracked URLs.
  const cases = amazonResolved
    .filter((r) => r.affiliate_url)
    .map(
      (r) =>
        `when ${sqlLiteral(r.normalized_product_page_url)} then ${sqlLiteral(r.affiliate_url)}`,
    )
    .join("\n      ");
  if (!cases) return null;
  const urlList = amazonResolved
    .filter((r) => r.affiliate_url)
    .map((r) => sqlLiteral(r.normalized_product_page_url))
    .join(", ");
  return `begin;
update public.images
set monetized_product_url_display = case product_page_url_display
      ${cases}
    end
where product_page_url_display in (${urlList})
  and (monetized_product_url_display is null or monetized_product_url_display = '');
commit;`;
}

// --- psql runner ------------------------------------------------------------
function runPsql(databaseUrl, sql) {
  const connection = postgresConnectionArgs(databaseUrl);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...connection.args, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", sql],
      {
        encoding: "utf8",
        env: { ...process.env, ...connection.env },
        maxBuffer: 1024 * 1024 * 100,
      },
    );
  } catch (err) {
    throw new Error(
      String(err.stderr || err.message || "").replaceAll(
        databaseUrl,
        redactDatabaseUrl(databaseUrl),
      ),
    );
  }
}

function runPsqlInChunks(databaseUrl, rows, chunkSize, buildSqlFn) {
  let total = 0;
  for (let i = 0; i < rows.length; i += chunkSize) {
    const chunk = rows.slice(i, i + chunkSize);
    runPsql(databaseUrl, buildSqlFn(chunk));
    total += chunk.length;
    process.stdout.write(`  wrote ${total}/${rows.length} rows\r`);
  }
  process.stdout.write("\n");
}

// --- working copy -----------------------------------------------------------
function loadWorkingCopy() {
  if (forceRefresh || !existsSync(workingCopyPath)) {
    console.log("Exporting fresh working copy …");
    execSync(`node ${path.join(repoRoot, "scripts", "export-product-pages-working-copy.mjs")} --format=ndjson`, {
      stdio: "inherit",
      cwd: repoRoot,
    });
  }
  return readFileSync(workingCopyPath, "utf8")
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));
}

// --- main -------------------------------------------------------------------
async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot });
  printGuardSummary(guard, { prefix: "Affiliate link resolver guard" });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);

  console.log(`Amazon Associates tag: ${AMAZON_TAG}`);
  console.log(`Mode: ${apply ? "apply" : "dry-run"}`);
  if (amazonOnly) console.log("Scope: Amazon rows only");
  if (backfillImages) console.log("Images backfill: enabled");

  console.log("\nLoading AWIN advertiser data …");
  const awinMap = loadAwinAdvertisers(awinAdvertiserCsvs);
  console.log(`  ${awinMap.size} AWIN advertiser domains loaded`);

  console.log("Loading Sovrn merchant data …");
  const sovrnMap = loadSovrnMerchants(sovrnCsvs);
  console.log(`  ${sovrnMap.size} Sovrn merchant domains loaded`);

  console.log("Loading product pages working copy …");
  const rows = loadWorkingCopy();
  console.log(`  ${rows.length} product pages loaded`);

  const toResolve = amazonOnly
    ? rows.filter((r) => /\bamazon\./i.test(String(r.normalized_product_page_url || "")))
    : rows;

  console.log(`\nResolving affiliate links for ${toResolve.length} rows …`);
  const resolved = toResolve.map((r) => resolveRow(r, awinMap, sovrnMap));

  // Summary
  const counts = {};
  let noAsin = 0;
  for (const r of resolved) {
    const key = r.affiliate_network ?? "none";
    counts[key] = (counts[key] || 0) + 1;
    if (/\bamazon\./i.test(r.normalized_product_page_url) && !r.affiliate_url) {
      noAsin++;
    }
  }
  console.log("\nResolution summary:");
  for (const [network, count] of Object.entries(counts).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${network}: ${count}`);
  }
  if (noAsin) console.log(`  amazon rows with no ASIN extractable: ${noAsin}`);

  const amazonResolved = resolved.filter((r) => r.affiliate_network === "amazon_associates");
  console.log(`\nAmazon affiliate URLs generated: ${amazonResolved.length}`);

  // Write report
  const reportsDir = path.join(fwmDataDir, "_reports");
  await mkdir(reportsDir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "").slice(0, 15) + "Z";
  const reportPath = path.join(reportsDir, `affiliate_link_resolution_${ts}.json`);
  const report = {
    generated_at: new Date().toISOString(),
    mode: apply ? "apply" : "dry-run",
    amazon_only: amazonOnly,
    backfill_images: backfillImages,
    amazon_tag: AMAZON_TAG,
    total_rows: rows.length,
    resolved_rows: resolved.length,
    network_counts: counts,
    amazon_no_asin_count: noAsin,
    sample_amazon: amazonResolved.slice(0, 5).map((r) => ({
      id: r.id,
      url: r.normalized_product_page_url,
      affiliate_url: r.affiliate_url,
    })),
  };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(`\nReport: ${reportPath}`);

  if (!apply) {
    console.log("\nDry-run complete. No rows written.");
    console.log("Re-run with --apply to write to staging.product_pages.");
    if (backfillImages)
      console.log("--backfill-images requires --apply to do anything.");
    return;
  }

  requireExplicitWriteFlag();

  console.log("\nWriting to staging.product_pages …");
  runPsqlInChunks(process.env.DEV_DATABASE_URL, resolved, 500, buildUpdateSql);
  console.log(`Wrote ${resolved.length} rows to staging.product_pages.`);

  if (backfillImages && amazonResolved.length) {
    const imagesSql = buildImagesBackfillSql(amazonResolved);
    if (imagesSql) {
      console.log(`\nBackfilling public.images for ${amazonResolved.filter((r) => r.affiliate_url).length} Amazon pages …`);
      runPsql(process.env.DEV_DATABASE_URL, imagesSql);
      console.log("Done.");
    }
  }

  console.log("\nApply complete.");
}

main().catch((err) => {
  console.error(err.message || err);
  process.exitCode = 1;
});
