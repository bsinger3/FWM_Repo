#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import {
  PRODUCTION_SUPABASE_REF,
  assertApprovedDevSupabase,
  callSupabaseRest,
  printGuardSummary,
} from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

async function readManifest(manifestPath) {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (manifest.source_supabase_project_ref !== PRODUCTION_SUPABASE_REF) {
    throw new Error(`Manifest source ref mismatch: ${manifest.source_supabase_project_ref}`);
  }
  if (manifest.source_table !== "public.images") {
    throw new Error(`Manifest source_table must be public.images, got ${manifest.source_table}`);
  }
  if (!existsSync(manifest.export_file_path)) {
    throw new Error(`Baseline export file is missing: ${manifest.export_file_path}`);
  }
  const actualSha = await sha256File(manifest.export_file_path);
  if (actualSha !== manifest.export_file_sha256) {
    throw new Error(`Baseline export SHA-256 mismatch. Expected ${manifest.export_file_sha256}, got ${actualSha}`);
  }
  return manifest;
}

async function getDevImageCount(guard) {
  const { response } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "images",
    method: "GET",
    searchParams: { select: "id", limit: "1" },
    prefer: "count=exact",
  });
  const count = Number((response.headers.get("content-range") || "").split("/").at(-1));
  return Number.isFinite(count) ? count : null;
}

function sampleBaselineRowsFromDump(sql, sampleLimit) {
  const rows = [];
  const insertPattern = /INSERT INTO public\.images \(([^)]+)\) VALUES \(([\s\S]*?)\);/g;
  let match;
  while ((match = insertPattern.exec(sql)) && rows.length < sampleLimit) {
    const columns = match[1].split(",").map((column) => column.trim().replace(/^"|"$/g, ""));
    const values = splitSqlValues(match[2]);
    const row = Object.fromEntries(columns.map((column, index) => [column, unquoteSqlValue(values[index])]));
    if (row.id) rows.push({
      id: row.id,
      original_url_display: row.original_url_display || null,
      product_page_url_display: row.product_page_url_display || null,
    });
  }
  return rows;
}

function splitSqlValues(valuesSql) {
  const values = [];
  let current = "";
  let inString = false;
  for (let i = 0; i < valuesSql.length; i += 1) {
    const char = valuesSql[i];
    const next = valuesSql[i + 1];
    if (char === "'") {
      current += char;
      if (inString && next === "'") {
        current += next;
        i += 1;
      } else {
        inString = !inString;
      }
    } else if (char === "," && !inString) {
      values.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  if (current) values.push(current.trim());
  return values;
}

function unquoteSqlValue(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed || /^null$/i.test(trimmed)) return null;
  if (trimmed.startsWith("'") && trimmed.endsWith("'")) {
    return trimmed.slice(1, -1).replace(/''/g, "'");
  }
  return trimmed;
}

async function fetchDevRowsByIds(guard, ids) {
  const rows = [];
  const chunkSize = 100;
  for (let index = 0; index < ids.length; index += chunkSize) {
    const chunk = ids.slice(index, index + chunkSize);
    if (!chunk.length) continue;
    const { data } = await callSupabaseRest({
      supabaseUrl: guard.supabaseUrl,
      serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      path: "images",
      method: "GET",
      searchParams: {
        select: "id,original_url_display,product_page_url_display",
        id: `in.(${chunk.join(",")})`,
      },
    });
    rows.push(...(Array.isArray(data) ? data : []));
  }
  return rows;
}

async function main() {
  const manifestArg = parseArg("manifest");
  if (!manifestArg) {
    throw new Error("Usage: node scripts/verify-dev-images-baseline.mjs --manifest=/path/to/manifest.json [--sample-limit=25|all] [--allow-extra-rows]");
  }
  const sampleLimitArg = parseArg("sample-limit", "25");
  const sampleLimit = sampleLimitArg === "all" ? Number.MAX_SAFE_INTEGER : Math.max(1, Number(sampleLimitArg) || 25);
  const allowExtraRows = hasFlag("allow-extra-rows");
  const manifestPath = path.resolve(manifestArg);
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Baseline verify guard" });

  const manifest = await readManifest(manifestPath);
  const devCount = await getDevImageCount(guard);
  const dumpSql = await readFile(manifest.export_file_path, "utf8");
  const sampleRows = sampleBaselineRowsFromDump(dumpSql, sampleLimit);
  const devRows = await fetchDevRowsByIds(guard, sampleRows.map((row) => row.id));
  const devRowsById = new Map(devRows.map((row) => [row.id, row]));
  const mismatches = sampleRows.filter((row) => {
    const dev = devRowsById.get(row.id);
    return !dev || dev.original_url_display !== row.original_url_display;
  });

  console.log(`Manifest: ${manifestPath}`);
  console.log(`Production manifest count: ${manifest.production_row_count}`);
  console.log(`Current dev public.images count: ${devCount ?? "unknown"}`);
  console.log(`Sampled baseline rows from dump: ${sampleRows.length}`);
  console.log(`Sample mismatches: ${mismatches.length}`);
  if (
    (!allowExtraRows && devCount !== manifest.production_row_count) ||
    (allowExtraRows && devCount < manifest.production_row_count)
  ) {
    throw new Error("Dev public.images count does not match the baseline manifest production_row_count.");
  }
  if (mismatches.length) {
    console.log(JSON.stringify(mismatches.slice(0, 10), null, 2));
    throw new Error("Sampled baseline IDs/URLs do not match dev.");
  }
  console.log("Baseline verification passed for count and sampled ID/URL checks.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
