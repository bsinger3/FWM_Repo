// Interactive height vs. weight dot-plot dashboard for dev image rows.
//
// READ-ONLY. Pulls every dev public.images row that has a height and/or weight
// and serves them to an interactive canvas scatter plot so we can eyeball
// outliers and obviously-wrong measurements (e.g. a 158" "height", a 600 lb
// "weight", points far off the human height/weight band).
//
// Dev-only: refuses to start unless SUPABASE_URL is the approved dev project.
// No writes of any kind.
//
//   npm run height-weight-dotplot        # http://127.0.0.1:4178

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertApprovedDevSupabase,
  callSupabaseRest,
  printGuardSummary,
} from "../../scripts/lib/dev-supabase-guard.mjs";

const __filename = fileURLToPath(import.meta.url);
const toolDir = path.dirname(__filename);
const publicDir = path.join(toolDir, "public");
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4178);

// Columns we pull for each point. Kept small so the whole set streams to the
// browser as one compact payload.
const SELECT_COLUMNS = [
  "id",
  "height_in_display",
  "weight_lbs_display",
  "size_display",
  "cupsize_display",
  "waist_in",
  "hips_in_display",
  "bust_in_display",
  "bra_band_in_display",
  "age_years_display",
  "source_site_display",
  "brand",
  "user_comment",
  "original_url_display",
  "product_page_url_display",
  "monetized_product_url_display",
].join(",");

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
]);

let pointsCache = null;

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store, max-age=0",
  });
  res.end(body);
}

function toNum(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

// Heights/weights are always positive; a stored 0 means "no value", not a real
// measurement, so treat it (and negatives) as missing to avoid fake origin dots.
function toPos(value) {
  const n = toNum(value);
  return n != null && n > 0 ? n : null;
}

// Pull every image row that has a height OR a weight, paging through the REST
// API. We keep rows with at least one of the two so the plot can also show
// "height only" / "weight only" rows on the axes if wanted; the client filters.
async function fetchAllPoints({ supabaseUrl, serviceRoleKey }) {
  const pageSize = 1000;
  let offset = 0;
  const rows = [];
  for (;;) {
    const { data } = await callSupabaseRest({
      supabaseUrl,
      serviceRoleKey,
      path: "images",
      searchParams: {
        select: SELECT_COLUMNS,
        or: "(height_in_display.gt.0,weight_lbs_display.gt.0)",
        order: "id.asc",
        limit: String(pageSize),
        offset: String(offset),
      },
    });
    if (!Array.isArray(data) || data.length === 0) break;
    for (const r of data) {
      rows.push({
        id: r.id,
        h: toPos(r.height_in_display),
        w: toPos(r.weight_lbs_display),
        size: r.size_display || null,
        cup: r.cupsize_display || null,
        waist: toNum(r.waist_in),
        hips: toNum(r.hips_in_display),
        bust: toNum(r.bust_in_display),
        band: toNum(r.bra_band_in_display),
        age: toNum(r.age_years_display),
        site: r.source_site_display || null,
        brand: r.brand || null,
        comment: r.user_comment || null,
        img: r.original_url_display || null,
        product: r.monetized_product_url_display || r.product_page_url_display || null,
      });
    }
    offset += data.length;
    if (data.length < pageSize) break;
  }
  return rows;
}

async function getPoints(guard) {
  if (pointsCache) return pointsCache;
  console.log("Fetching image rows from dev Supabase…");
  const rows = await fetchAllPoints({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
  });
  console.log(`Loaded ${rows.length} rows with a height and/or weight.`);
  pointsCache = { generatedAt: new Date().toISOString(), count: rows.length, points: rows };
  return pointsCache;
}

async function serveStatic(res, urlPath) {
  const rel = urlPath === "/" ? "/index.html" : urlPath;
  const filePath = path.join(publicDir, path.normalize(rel).replace(/^(\.\.[/\\])+/, ""));
  if (!filePath.startsWith(publicDir)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }
  try {
    const body = await readFile(filePath);
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, {
      "Content-Type": contentTypes.get(ext) || "application/octet-stream",
      "Cache-Control": "no-store, max-age=0",
    });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("Not found");
  }
}

async function main() {
  const guard = await assertApprovedDevSupabase({
    cwd: path.resolve(toolDir, "../.."),
    requireServiceRoleKey: true,
  });
  printGuardSummary(guard, { prefix: "height-weight-dotplot" });

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, `http://${host}:${port}`);
      if (url.pathname === "/api/points") {
        if (url.searchParams.get("refresh") === "1") pointsCache = null;
        const data = await getPoints(guard);
        sendJson(res, data);
        return;
      }
      await serveStatic(res, url.pathname);
    } catch (error) {
      console.error(error);
      sendJson(res, { error: String(error?.message || error) }, 500);
    }
  });

  server.listen(port, host, () => {
    console.log(`Height/weight dot plot: http://${host}:${port}`);
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
