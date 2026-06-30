#!/usr/bin/env node

// Tiny local server for the lighting calibration dashboard. Serves the reports
// directory statically (so the dashboard HTML loads) AND accepts the labels via
// POST /save-labels, writing them into FWM_Data/_reports/ where Claude can read
// them — so Bri's decisions don't have to detour through the Downloads folder.
//
// Read/write is confined to the reports dir. No Supabase, no network writes.
//   node scripts/lighting-label-server.mjs   (PORT defaults to 8791)

import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const ROOT = path.join(fwmDataDir(repoRoot), "_reports");
const PORT = Number(process.env.PORT || 8791);
const HOST = "127.0.0.1";
const MAX_BODY = 16 * 1024 * 1024; // 16MB cap on posted labels

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

function ts() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

// Resolve a URL path to a file inside ROOT, or null if it escapes ROOT.
function safePath(urlPath) {
  const decoded = decodeURIComponent(urlPath.split("?")[0]);
  const rel = decoded.replace(/^\/+/, "");
  const resolved = path.resolve(ROOT, rel || "index.html");
  if (resolved !== ROOT && !resolved.startsWith(ROOT + path.sep)) return null;
  return resolved;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(new Error("body too large"));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

const server = createServer(async (req, res) => {
  // CORS for same-origin localhost (harmless, keeps fetch happy across ports).
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "POST" && ["/save-labels", "/save-annotations"].includes(req.url.split("?")[0])) {
    try {
      const raw = await readBody(req);
      const parsed = JSON.parse(raw); // validate it is JSON before writing
      const count = Array.isArray(parsed.labels)
        ? parsed.labels.length
        : Array.isArray(parsed.annotations)
          ? parsed.annotations.length
          : null;
      // Caller can pick the file stem via save_name (sanitised); defaults by route.
      const stem = String(parsed.save_name || (req.url.includes("annotations") ? "prettiness_annotations" : "lighting_labels"))
        .replace(/[^a-z0-9_-]/gi, "_")
        .slice(0, 64);
      const filename = `${stem}_${ts()}.json`;
      const outPath = path.join(ROOT, filename);
      await mkdir(ROOT, { recursive: true });
      await writeFile(outPath, JSON.stringify(parsed, null, 2) + "\n", "utf8");
      console.log(`[save] wrote ${count ?? "?"} entries -> ${outPath}`);
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: true, path: outPath, filename, count }));
    } catch (error) {
      res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: false, error: String(error?.message || error) }));
    }
    return;
  }

  if (req.method !== "GET") {
    res.writeHead(405);
    res.end("method not allowed");
    return;
  }

  const filePath = safePath(req.url);
  if (!filePath) {
    res.writeHead(403);
    res.end("forbidden");
    return;
  }
  try {
    const data = await readFile(filePath);
    res.writeHead(200, { "Content-Type": TYPES[path.extname(filePath)] || "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("not found");
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Lighting label server on http://${HOST}:${PORT}/  (serving ${ROOT})`);
  console.log(`POST /save-labels writes lighting_labels_<ts>.json into that dir.`);
});
