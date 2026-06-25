// Flagged-image review dashboard (dev-guarded).
//
// Surfaces every image a reporter flagged with the 🚩 button — pulled from BOTH
// the prod and dev image_reports tables by build-dataset.mjs — so you can decide,
// per image, whether to REMOVE it (soft-hide in dev) or KEEP it.
//
// Decisions are persisted LOCALLY to data/decisions.json (in the repo, never
// Downloads). Nothing here writes to any database — the soft-hide is applied
// later by `npm run flagged-review:apply` reading that decisions file.
//
// Dev-only: refuses any non-dev Supabase. npm run flagged-review (port 4187).

import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertApprovedDevSupabase,
  assertApprovedDevDatabaseUrl,
  printGuardSummary,
} from "../../scripts/lib/dev-supabase-guard.mjs";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(toolDir, "public");
const dataDir = path.join(toolDir, "data");
const datasetPath = path.join(dataDir, "flagged-dataset.json");
const decisionsPath = path.join(dataDir, "decisions.json");
const repoRoot = path.resolve(toolDir, "../..");
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4187);

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
]);

const VALID_DECISIONS = new Set(["remove", "keep", "undecided"]);

function sendJson(res, data, status = 200) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(JSON.stringify(data));
}

async function loadDecisions() {
  if (!existsSync(decisionsPath)) return {};
  try {
    return JSON.parse(await readFile(decisionsPath, "utf8"));
  } catch {
    return {};
  }
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
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
  printGuardSummary(guard, { prefix: "flagged-image-review" });

  if (!existsSync(datasetPath)) {
    console.error(`\nDataset missing. Run:  npm run flagged-review:build\n  (expected at ${datasetPath})`);
    process.exit(1);
  }

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, `http://${host}:${port}`);

      if (url.pathname === "/api/dataset" && req.method === "GET") {
        const dataset = JSON.parse(await readFile(datasetPath, "utf8"));
        const decisions = await loadDecisions();
        return sendJson(res, { dataset, decisions });
      }

      if (url.pathname === "/api/decision" && req.method === "POST") {
        const { image_id, decision, note } = await readBody(req);
        if (!image_id || !VALID_DECISIONS.has(decision)) {
          return sendJson(res, { error: "image_id and a valid decision (remove|keep|undecided) are required" }, 400);
        }
        const decisions = await loadDecisions();
        if (decision === "undecided") {
          delete decisions[image_id];
        } else {
          decisions[image_id] = {
            decision,
            note: typeof note === "string" ? note : "",
            updatedAt: new Date().toISOString(),
          };
        }
        await writeFile(decisionsPath, JSON.stringify(decisions, null, 2));
        const summary = { remove: 0, keep: 0 };
        for (const d of Object.values(decisions)) if (summary[d.decision] != null) summary[d.decision] += 1;
        return sendJson(res, { ok: true, decisions, summary });
      }

      await serveStatic(res, url.pathname);
    } catch (e) {
      console.error(e);
      sendJson(res, { error: String(e?.message || e) }, 500);
    }
  });

  server.listen(port, host, () => {
    console.log(`Flagged-image review dashboard: http://${host}:${port}`);
    console.log(`Decisions saved to: ${path.relative(repoRoot, decisionsPath)}`);
  });
}

main().catch((e) => { console.error(e); process.exit(1); });
