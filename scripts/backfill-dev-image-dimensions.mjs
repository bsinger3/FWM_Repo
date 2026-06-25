#!/usr/bin/env node
/**
 * Backfill real source pixel dimensions for dev public.images (dev-only).
 *
 * Why: public.images.width/height (text) are empty, so the DB can't tell a
 * 600px source photo from a 2000px one. That blind spot is exactly what lets
 * low-res photos survive the garment-aware auto-crop zoom and surface pixelated
 * in search. This script probes each image's header bytes (no full decode) to
 * recover intrinsic width/height, then writes them to the numeric columns added
 * by 20260625_dev_26_image_source_dimensions.sql (source_width_px /
 * source_height_px / dimensions_checked_at / dimensions_source).
 *
 * Two phases, controlled by flags:
 *   (default)   FETCH  — read candidate rows from dev, range-fetch each image's
 *                        header, parse W/H, append results to a resumable JSONL
 *                        stage file. No DB writes. Safe to re-run / interrupt.
 *   --apply     APPLY  — read the stage file and UPDATE public.images in dev.
 *                        Gated: requires FWM_DEV_DB_WRITE_OK + the dev ref.
 *
 * Flags:
 *   --limit=N        cap candidate rows this run (default: all)
 *   --concurrency=N  parallel fetches (default 24)
 *   --refetch        re-probe even images that already have source_width_px
 *   --apply          run the APPLY phase instead of FETCH
 *
 * Stage file: $FWM_DATA_DIR/_reports/dev_image_source_dimensions.jsonl
 * Dev-only: refuses any DB URL that isn't the approved dev project ref.
 */
import { execFileSync } from "node:child_process";
import { appendFile, readFile, mkdir } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadDotEnv } from "./lib/local-env.mjs";
import {
  assertApprovedDevDatabaseUrl,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs, redactDatabaseUrl } from "./lib/postgres-client.mjs";
import { parseImageMetadata } from "./lib/image-dimensions.mjs";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
await loadDotEnv({ cwd: repoRoot });

const argOf = (name, dflt) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : dflt;
};
const apply = process.argv.includes("--apply");
const refetch = process.argv.includes("--refetch");
const limit = Number(argOf("limit", "0")) || 0;
const concurrency = Math.max(1, Number(argOf("concurrency", "24")) || 24);
const timeoutMs = Math.max(2000, Number(argOf("timeout", "15000")) || 15000);

const stageDir = path.join(fwmDataDir(repoRoot), "_reports");
const stagePath = path.join(stageDir, "dev_image_source_dimensions.jsonl");

function databaseUrl() {
  const url = process.env.DEV_DATABASE_URL;
  if (!url) throw new Error("DEV_DATABASE_URL is not set.");
  if (process.env.PROD_DATABASE_URL && url === process.env.PROD_DATABASE_URL) {
    throw new Error("Refusing to run: DEV_DATABASE_URL equals PROD_DATABASE_URL.");
  }
  assertApprovedDevDatabaseUrl(url);
  return url;
}

function runPsql(url, sql) {
  const c = postgresConnectionArgs(url);
  try {
    return execFileSync(
      postgresClientTool("psql"),
      [...c.args, "--set", "ON_ERROR_STOP=1", "--no-align", "--tuples-only", "--field-separator", "\t", "--command", sql],
      { encoding: "utf8", env: { ...process.env, ...c.env }, maxBuffer: 1024 * 1024 * 256 },
    );
  } catch (e) {
    throw new Error(String(e.stderr || e.message || "").replaceAll(url, redactDatabaseUrl(url)));
  }
}

const sqlString = (v) => (v == null ? "null" : `'${String(v).replaceAll("'", "''")}'`);

// Read the ids we've already resolved (or terminally failed) from the stage file,
// so an interrupted run resumes instead of refetching.
function loadStagedIds() {
  const done = new Set();
  if (!existsSync(stagePath)) return done;
  const text = readFileSync(stagePath, "utf8");
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const rec = JSON.parse(t);
      if (rec && rec.id) done.add(rec.id);
    } catch {
      /* skip malformed line */
    }
  }
  return done;
}

async function fetchHeader(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      redirect: "follow",
      headers: {
        "User-Agent": "FWMDevDimensionBackfill/0.1 (+https://friendswithmeasurements.com)",
        Range: "bytes=0-1048575",
      },
    });
    const buf = Buffer.from(await response.arrayBuffer());
    return {
      ok: response.ok || response.status === 206,
      status: response.status,
      content_type: response.headers.get("content-type") || "",
      bytes: buf,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function probe(row) {
  const rec = { id: row.id, w: null, h: null, fmt: null, status: null, ct: null, err: null };
  try {
    const res = await fetchHeader(row.url);
    rec.status = res.status;
    rec.ct = res.content_type;
    if (!res.ok) {
      rec.err = `http_${res.status}`;
      return rec;
    }
    const meta = parseImageMetadata(res.bytes, res.content_type);
    if (meta.width && meta.height && meta.width > 0 && meta.height > 0) {
      rec.w = meta.width;
      rec.h = meta.height;
      rec.fmt = meta.format || null;
    } else {
      rec.err = "no_dimensions";
    }
  } catch (e) {
    rec.err = (e && e.name === "AbortError") ? "timeout" : String(e && e.message || e).slice(0, 120);
  }
  return rec;
}

// Bounded-concurrency map that flushes each result to the stage file as it lands.
async function runPool(rows) {
  let next = 0;
  let done = 0;
  let ok = 0;
  let fail = 0;
  const total = rows.length;
  const t0 = Date.now();
  async function worker() {
    while (next < rows.length) {
      const row = rows[next++];
      const rec = await probe(row);
      rec.at = new Date(Date.now()).toISOString();
      await appendFile(stagePath, JSON.stringify(rec) + "\n", "utf8");
      done++;
      if (rec.w) ok++; else fail++;
      if (done % 250 === 0 || done === total) {
        const rate = done / Math.max(1, (Date.now() - t0) / 1000);
        const eta = Math.round((total - done) / Math.max(0.01, rate));
        console.log(`  ${done}/${total}  ok=${ok} fail=${fail}  ${rate.toFixed(1)}/s  eta ${eta}s`);
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, rows.length) }, worker));
  return { ok, fail };
}

async function phaseFetch(url) {
  await mkdir(stageDir, { recursive: true });
  const where = refetch
    ? "original_url_display is not null and btrim(original_url_display) <> ''"
    : "original_url_display is not null and btrim(original_url_display) <> '' and source_width_px is null";
  const sql = `select id::text, original_url_display from public.images where ${where} order by id ${limit ? `limit ${limit}` : ""};`;
  const raw = runPsql(url, sql).trim();
  let rows = raw ? raw.split("\n").map((line) => {
    const [id, ...rest] = line.split("\t");
    return { id, url: rest.join("\t") };
  }) : [];

  const staged = refetch ? new Set() : loadStagedIds();
  const before = rows.length;
  rows = rows.filter((r) => r.id && r.url && !staged.has(r.id));
  console.log(`FETCH: ${before} candidate rows, ${staged.size} already staged, ${rows.length} to probe (concurrency ${concurrency}).`);
  console.log(`Stage file: ${stagePath}`);
  if (!rows.length) {
    console.log("Nothing to fetch. (Use --refetch to re-probe everything.)");
    return;
  }
  const { ok, fail } = await runPool(rows);
  console.log(`FETCH done. ok=${ok} fail=${fail}. Review the stage file, then re-run with --apply.`);
}

function loadStageRecords() {
  if (!existsSync(stagePath)) throw new Error(`No stage file at ${stagePath}. Run the FETCH phase first.`);
  const out = new Map(); // id -> latest record (last write wins)
  for (const line of readFileSync(stagePath, "utf8").split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      const rec = JSON.parse(t);
      if (rec && rec.id) out.set(rec.id, rec);
    } catch {
      /* skip */
    }
  }
  return out;
}

async function phaseApply(url) {
  requireExplicitWriteFlag();
  const records = [...loadStageRecords().values()];
  const usable = records.filter((r) => Number.isFinite(r.w) && Number.isFinite(r.h) && r.w > 0 && r.h > 0);
  const failed = records.length - usable.length;
  console.log(`APPLY: ${records.length} staged records, ${usable.length} with dimensions, ${failed} without.`);
  if (!usable.length) {
    console.log("No usable dimensions to write.");
    return;
  }

  // Batched UPDATE ... FROM (VALUES ...) so one statement touches many rows.
  const CHUNK = 1000;
  let written = 0;
  for (let i = 0; i < usable.length; i += CHUNK) {
    const chunk = usable.slice(i, i + CHUNK);
    const values = chunk
      .map((r) => `(${sqlString(r.id)}::uuid, ${Math.round(r.w)}, ${Math.round(r.h)}, ${sqlString(r.fmt || "header_fetch")})`)
      .join(",\n");
    const sql = `
      update public.images i set
        source_width_px = v.w,
        source_height_px = v.h,
        dimensions_checked_at = now(),
        dimensions_source = 'header_fetch:' || v.fmt
      from (values\n${values}\n) as v(id, w, h, fmt)
      where i.id = v.id;`;
    runPsql(url, sql);
    written += chunk.length;
    console.log(`  applied ${written}/${usable.length}`);
  }

  const summary = runPsql(url, `
    select
      count(*) filter (where source_width_px is not null) as with_dims,
      count(*) as total
    from public.images;`).trim();
  console.log(`APPLY done. images with dimensions / total = ${summary.replaceAll("\t", " / ")}`);
}

async function main() {
  const url = databaseUrl();
  if (apply) await phaseApply(url);
  else await phaseFetch(url);
}

main().catch((e) => {
  console.error(String(e && e.message || e));
  process.exit(1);
});
