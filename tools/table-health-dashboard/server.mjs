// Table-health dashboard for the dev public.images table (READ-ONLY, dev-guarded).
//
// Visualizes data completeness and quality:
//   - per-column fill rate (how many rows have each field)
//   - a missingness matrix (sampled rows x fields heatmap) ordered by source so
//     source-correlated gaps are visible
//   - quality-flag counts (the garbage classes: age<13, bad image url, cup junk,
//     out-of-band measurements, file-path comments, ...)
//   - a filterable spreadsheet grid (click a column or flag to drill in)
//
// Dev-only: refuses any non-dev DB. No writes. npm run table-health (port 4179).

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  printGuardSummary,
} from "../../scripts/lib/dev-supabase-guard.mjs";
import { postgresClientTool, postgresConnectionArgs } from "../../scripts/lib/postgres-client.mjs";

const __filename = fileURLToPath(import.meta.url);
const toolDir = path.dirname(__filename);
const publicDir = path.join(toolDir, "public");
const repoRoot = path.resolve(toolDir, "../..");
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4179);
const TABLE = "public.images";

// Curated content columns (label shown in the UI). present = non-null & non-empty.
const COLUMNS = [
  { key: "original_url_display", label: "image url", group: "links" },
  { key: "product_page_url_display", label: "product url", group: "links" },
  { key: "monetized_product_url_display", label: "affiliate url", group: "links" },
  { key: "source_site_display", label: "source", group: "links" },
  { key: "user_comment", label: "comment", group: "content" },
  { key: "size_display", label: "size", group: "content" },
  { key: "brand", label: "brand", group: "content" },
  { key: "color_display", label: "color", group: "content" },
  { key: "clothing_type_id", label: "clothing type", group: "content" },
  { key: "height_in_display", label: "height", group: "measure" },
  { key: "weight_lbs_display", label: "weight", group: "measure" },
  { key: "waist_in", label: "waist", group: "measure" },
  { key: "hips_in_display", label: "hips", group: "measure" },
  { key: "bust_in_display", label: "bust", group: "measure" },
  { key: "bra_band_in_display", label: "bra band", group: "measure" },
  { key: "cupsize_display", label: "cup", group: "measure" },
  { key: "inseam_inches_display", label: "inseam", group: "measure" },
  { key: "age_years_display", label: "age", group: "measure" },
  { key: "weeks_pregnant", label: "weeks preg", group: "measure" },
  { key: "crop_spec", label: "crop", group: "cv" },
  { key: "full_body_visible", label: "full body", group: "cv" },
  { key: "prettiness_score", label: "prettiness", group: "cv" },
  { key: "image_orientation_degrees", label: "orientation", group: "cv" },
];

// Universal "present" expression — works for text/numeric/bool/json columns.
const present = (k) => `(${k} is not null and ${k}::text <> '')`;

// Quality flags (the garbage classes). Each is a SQL predicate over a row.
const VALID_CUP = "'^(AAA|AA|A|B|C|D|DD|DDD|DDDD|E|F|G|H|I|J|K|DDD/E|DDD/F|DD/E)$'";
const FLAGS = [
  { key: "comment_is_path", label: "comment is a file path",
    where: `user_comment is not null and (user_comment like '/Users/%' or (user_comment like '%/%' and user_comment like '%.csv'))` },
  { key: "bad_image_url", label: "image url not http(s)",
    where: `original_url_display is not null and original_url_display !~* '^https?://'` },
  { key: "age_lt13", label: "age < 13 (likely false positive)",
    where: `age_years_display between 1 and 12` },
  { key: "weight_zero", label: "weight = 0", where: `weight_lbs_display = 0` },
  { key: "cup_junk", label: "cup size not a valid cup",
    where: `cupsize_display is not null and cupsize_display <> '' and cupsize_display !~ ${VALID_CUP}` },
  { key: "height_oob", label: "height outside 48–84 in",
    where: `height_in_display is not null and (height_in_display < 48 or height_in_display > 84)` },
  { key: "weight_oob", label: "weight outside 60–400 lb",
    where: `weight_lbs_display is not null and weight_lbs_display > 0 and (weight_lbs_display < 60 or weight_lbs_display > 400)` },
  { key: "waist_oob", label: "waist outside 18–60 in",
    where: `waist_in ~ '^[0-9.]+$' and (waist_in::numeric < 18 or waist_in::numeric > 60)` },
  { key: "bodymeasure_oob", label: "hips/bust/band impossible",
    where: `hips_in_display > 75 or bust_in_display > 60 or bra_band_in_display > 54 or bust_in_number_display > 60` },
];

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
]);

let dbUrl = null;
function runJson(sql) {
  const conn = postgresConnectionArgs(dbUrl);
  const r = spawnSync(postgresClientTool("psql"), [...conn.args, "-tA", "-v", "ON_ERROR_STOP=1", "-c", sql], {
    encoding: "utf8",
    env: { ...process.env, ...conn.env },
    maxBuffer: 1024 * 1024 * 64,
  });
  if (r.status !== 0) throw new Error(r.stderr || "psql failed");
  const out = r.stdout.trim();
  return out ? JSON.parse(out) : null;
}

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(body);
}

let healthCache = null;
function getHealth() {
  if (healthCache) return healthCache;
  const colJson = COLUMNS.map((c) => `'${c.key}', count(*) filter (where ${present(c.key)})`).join(", ");
  const flagJson = FLAGS.map((f) => `'${f.key}', count(*) filter (where ${f.where})`).join(", ");
  const anyFlag = FLAGS.map((f) => `(${f.where})`).join(" or ");
  const sql = `select json_build_object(
    'total', count(*),
    'flaggedRows', count(*) filter (where ${anyFlag}),
    'columns', json_build_object(${colJson}),
    'flags', json_build_object(${flagJson})
  ) from ${TABLE};`;
  const data = runJson(sql);
  healthCache = {
    generatedAt: new Date().toISOString(),
    total: data.total,
    flaggedRows: data.flaggedRows,
    columns: COLUMNS.map((c) => ({ ...c, present: data.columns[c.key], pct: data.total ? data.columns[c.key] / data.total : 0 })),
    flags: FLAGS.map((f) => ({ key: f.key, label: f.label, count: data.flags[f.key] })),
  };
  return healthCache;
}

let sampleCache = null;
function getSample(n = 2000) {
  if (sampleCache) return sampleCache;
  const bits = COLUMNS.map((c) => `${present(c.key)} as ${c.key}`).join(", ");
  const sql = `with ranked as (
      select ${bits}, source_site_display as src,
        row_number() over (order by source_site_display, id) rn, count(*) over () total
      from ${TABLE}
    )
    select coalesce(json_agg(json_build_object(
      'src', src, ${COLUMNS.map((c) => `'${c.key}', ${c.key}`).join(", ")}
    ) order by rn), '[]'::json)
    from ranked
    where rn % greatest(1, (total / ${n})::int) = 1;`;
  const rows = runJson(sql) || [];
  const clean = (s) => String(s || "?").replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
  sampleCache = {
    columns: COLUMNS,
    rows: rows.map((r) => COLUMNS.map((c) => (r[c.key] ? 1 : 0))),
    sources: rows.map((r) => clean(r.src)),
  };
  return sampleCache;
}

function getRows(url) {
  const limit = Math.min(Number(url.searchParams.get("limit")) || 60, 300);
  const offset = Math.max(Number(url.searchParams.get("offset")) || 0, 0);
  const missing = url.searchParams.get("missing"); // a column key
  const flag = url.searchParams.get("flag"); // a flag key
  let where = "true";
  if (missing && COLUMNS.some((c) => c.key === missing)) where = `not ${present(missing)}`;
  else if (flag) {
    const f = FLAGS.find((x) => x.key === flag);
    if (f) where = `(${f.where})`;
  }
  const cols = ["id", ...COLUMNS.map((c) => c.key)];
  const flagExprs = FLAGS.map((f) => `(${f.where}) as flag_${f.key}`).join(", ");
  const sql = `with q as (select ${cols.join(", ")}, ${flagExprs} from ${TABLE} where ${where})
    select json_build_object(
      'count', (select count(*) from q),
      'rows', coalesce((select json_agg(row_to_json(t)) from (
        select * from q order by id limit ${limit} offset ${offset}
      ) t), '[]'::json)
    );`;
  return runJson(sql);
}

async function serveStatic(res, urlPath) {
  const rel = urlPath === "/" ? "/index.html" : urlPath;
  const filePath = path.join(publicDir, path.normalize(rel).replace(/^(\.\.[/\\])+/, ""));
  if (!filePath.startsWith(publicDir)) { res.writeHead(403); res.end("Forbidden"); return; }
  try {
    const body = await readFile(filePath);
    res.writeHead(200, { "Content-Type": contentTypes.get(path.extname(filePath)) || "application/octet-stream", "Cache-Control": "no-store" });
    res.end(body);
  } catch { res.writeHead(404); res.end("Not found"); }
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: false });
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);
  dbUrl = process.env.DEV_DATABASE_URL;
  printGuardSummary(guard, { prefix: "table-health" });

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, `http://${host}:${port}`);
      if (url.pathname === "/api/health") {
        if (url.searchParams.get("refresh") === "1") { healthCache = null; sampleCache = null; }
        return sendJson(res, getHealth());
      }
      if (url.pathname === "/api/sample") return sendJson(res, getSample());
      if (url.pathname === "/api/rows") return sendJson(res, getRows(url));
      await serveStatic(res, url.pathname);
    } catch (e) {
      console.error(e);
      sendJson(res, { error: String(e?.message || e) }, 500);
    }
  });
  server.listen(port, host, () => console.log(`Table-health dashboard: http://${host}:${port}`));
}

main().catch((e) => { console.error(e); process.exit(1); });
