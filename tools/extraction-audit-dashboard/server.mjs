#!/usr/bin/env node
// Read-only dashboard for auditing measurement extraction on approved review
// images. Shows the image, the full review comment (numbers + measurement words
// colour-coded by whether we captured them), and the extracted measurements.
// The reviewer flags rows whose extraction is wrong; flags persist to disk and
// seed the deterministic regex tests we add next.
//
// Build the dataset first:  node tools/extraction-audit-dashboard/build-dataset.mjs
// Then run:                 npm run extraction-audit   (default port 4175)

import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../image-review-dashboard/paths.mjs";

const __filename = fileURLToPath(import.meta.url);
const toolDir = path.dirname(__filename);
const repoRoot = path.resolve(toolDir, "../..");
const publicDir = path.join(toolDir, "public");
const dataDir = path.join(fwmDataDir(repoRoot), "_reports", "extraction_audit");
const datasetPath = path.join(dataDir, "dataset.json");
const flagsPath = path.join(dataDir, "flags.json");
const port = Number(process.env.PORT || 4175);

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

let dataset = null;
let flags = {};

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  res.end(body);
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function loadDataset() {
  if (!existsSync(datasetPath)) {
    throw new Error(
      `Dataset not found at ${datasetPath}. Run: node tools/extraction-audit-dashboard/build-dataset.mjs`,
    );
  }
  dataset = JSON.parse(await readFile(datasetPath, "utf8"));
  // The builder assigns a stable comment-based id; only synthesize one if absent.
  dataset.rows.forEach((r) => {
    if (!r.id) r.id = `r_${r.bucket}::${r.partFile}::${r.rowKey}`;
  });
  if (existsSync(flagsPath)) {
    flags = JSON.parse(await readFile(flagsPath, "utf8"));
  }
  // Migrate the old {bad:true} flag shape to the review-state shape.
  let migrated = false;
  for (const [id, f] of Object.entries(flags)) {
    if (f && !f.state) {
      flags[id] = { state: f.bad ? "incorrect" : "correct", note: f.note || "", ts: f.ts || new Date().toISOString() };
      migrated = true;
    }
  }
  if (migrated) await saveFlags();
}

// A row is "reviewed" once it has any state (correct or incorrect).
function reviewState(id) {
  return flags[id]?.state || "";
}

async function saveFlags() {
  await mkdir(dataDir, { recursive: true });
  await writeFile(flagsPath, JSON.stringify(flags, null, 2));
}

function siteCounts() {
  const counts = new Map();
  for (const r of dataset.rows) {
    const s = r.sourceSite || "(unknown)";
    counts.set(s, (counts.get(s) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([site, count]) => ({ site, count }))
    .sort((a, b) => b.count - a.count);
}

// Returns ids (in display order) matching the filters. `status` defaults to
// "unreviewed" so rows already judged (correct OR incorrect) never reappear.
function matchIds(query) {
  const { site, q, minSuspicion } = query;
  const status = query.status || "unreviewed";
  const needle = (q || "").trim().toLowerCase();
  const min = Number(minSuspicion || 0);
  const ids = [];
  for (const r of dataset.rows) {
    const st = reviewState(r.id);
    if (status === "unreviewed" && st) continue;
    if (status === "correct" && st !== "correct") continue;
    if (status === "incorrect" && st !== "incorrect") continue;
    // status === "all" -> no state filter
    if (query.commented === "commented" && !r.reviewNote) continue;
    if (site && r.sourceSite !== site) continue;
    if (min && r.suspicion < min) continue;
    if (needle) {
      const hay = `${r.comment} ${r.reviewNote} ${r.brand} ${r.clothingType}`.toLowerCase();
      if (!hay.includes(needle)) continue;
    }
    ids.push(r.id);
  }
  return ids;
}

function decorate(r) {
  return { ...r, flag: flags[r.id] || null };
}

async function handleApi(req, res, url) {
  if (req.method === "GET" && url.pathname === "/api/meta") {
    let correct = 0;
    let incorrect = 0;
    for (const f of Object.values(flags)) {
      if (f?.state === "correct") correct += 1;
      else if (f?.state === "incorrect") incorrect += 1;
    }
    return sendJson(res, {
      built_at: dataset.built_at,
      counts: dataset.counts,
      total: dataset.rows.length,
      sites: siteCounts(),
      reviewed: { correct, incorrect, unreviewed: dataset.rows.length - correct - incorrect },
    });
  }

  // The full ordered id list for a filter — the client paginates this locally so
  // marking a row removes it without skipping or re-showing others.
  if (req.method === "GET" && url.pathname === "/api/queue") {
    const ids = matchIds(Object.fromEntries(url.searchParams));
    return sendJson(res, { total: ids.length, ids });
  }

  // Full row data for a batch of ids (POST so long id lists aren't URL-capped).
  if (req.method === "POST" && url.pathname === "/api/rows") {
    const body = await readJsonBody(req);
    const ids = Array.isArray(body.ids) ? body.ids : [];
    const byId = new Map(dataset.rows.map((r) => [r.id, r]));
    const rows = ids.map((id) => byId.get(id)).filter(Boolean).map(decorate);
    return sendJson(res, { rows });
  }

  if (req.method === "POST" && url.pathname === "/api/flag") {
    const body = await readJsonBody(req);
    const { id } = body;
    if (!id) return sendJson(res, { error: "id required" }, 400);
    const state = ["correct", "incorrect"].includes(body.state) ? body.state : "";
    const note = String(body.note || "");
    if (!state && !note.trim()) delete flags[id];
    else flags[id] = { state, note, ts: new Date().toISOString() };
    await saveFlags();
    return sendJson(res, { ok: true, flag: flags[id] || null });
  }

  if (req.method === "GET" && url.pathname === "/api/export") {
    const out = dataset.rows
      .filter((r) => flags[r.id]?.state === "incorrect")
      .map((r) => ({
        id: r.id,
        rowKey: r.rowKey,
        sourceSite: r.sourceSite,
        comment: r.comment,
        extracted: r.extracted,
        mentionedTypes: r.mentionedTypes,
        reviewNote: r.reviewNote,
        reviewerFlagNote: flags[r.id]?.note || "",
      }));
    // Write into the data repo (not the browser's Downloads folder).
    await mkdir(dataDir, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, "").replace(/-/g, "");
    const file = path.join(dataDir, `flagged_extractions_${stamp}.json`);
    const latest = path.join(dataDir, "flagged_extractions.latest.json");
    const body = JSON.stringify({ exported_at: new Date().toISOString(), count: out.length, rows: out }, null, 2);
    await writeFile(file, body);
    await writeFile(latest, body);
    return sendJson(res, { ok: true, count: out.length, path: file, latest });
  }

  return sendJson(res, { error: "not found" }, 404);
}

async function serveStatic(req, res, url) {
  let rel = url.pathname === "/" ? "/index.html" : url.pathname;
  const filePath = path.join(publicDir, path.normalize(rel));
  if (!filePath.startsWith(publicDir) || !existsSync(filePath)) {
    res.writeHead(404);
    return res.end("Not found");
  }
  const ext = path.extname(filePath);
  const body = await readFile(filePath);
  res.writeHead(200, { "Content-Type": contentTypes[ext] || "application/octet-stream" });
  res.end(body);
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${port}`);
    if (url.pathname.startsWith("/api/")) return await handleApi(req, res, url);
    return await serveStatic(req, res, url);
  } catch (err) {
    sendJson(res, { error: String(err?.message || err) }, 500);
  }
});

loadDataset()
  .then(() => {
    server.listen(port, () => {
      console.log(`Extraction-audit dashboard: http://localhost:${port}`);
      console.log(
        `  ${dataset.rows.length} checkable rows | built ${dataset.built_at} | flags: ${flagsPath}`,
      );
    });
  })
  .catch((err) => {
    console.error(err.message);
    process.exit(1);
  });
