#!/usr/bin/env node
/**
 * Approval dashboard for the dev staging.product_pages rows still bucketed as
 * mother_category_id = 'other' (the catch-all clothing bucket).
 *
 * For each row it shows the product name + all the taxonomy signal we have, plus
 * a SUGGESTED mother category (other than 'other') from build-dataset.mjs. You
 * can approve the suggestion, pick a different existing category from a dropdown,
 * or type a brand-new category. A "select all" control approves in bulk.
 *
 * Decisions persist LOCALLY to data/decisions.json (in the repo, never
 * Downloads). NOTHING here writes to any database — apply them later with
 *   node scripts/apply-dev-other-category-approvals.mjs   (dry-run by default).
 *
 * Dev-only: refuses any non-dev Supabase.  npm run other-category-review (4196).
 */

import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertApprovedDevSupabase, printGuardSummary } from "../../scripts/lib/dev-supabase-guard.mjs";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(toolDir, "public");
const dataDir = path.join(toolDir, "data");
const datasetPath = path.join(dataDir, "other-category-dataset.json");
const decisionsPath = path.join(dataDir, "decisions.json");
const repoRoot = path.resolve(toolDir, "..", "..");
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4196);

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
]);

function sendJson(res, data, status = 200) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(JSON.stringify(data));
}

async function loadDataset() {
  if (!existsSync(datasetPath)) {
    throw new Error(
      `Dataset missing: ${path.relative(repoRoot, datasetPath)}. Run: node tools/other-category-approval/build-dataset.mjs`,
    );
  }
  return JSON.parse(await readFile(datasetPath, "utf8"));
}

async function loadDecisions() {
  if (!existsSync(decisionsPath)) return {};
  try {
    return JSON.parse(await readFile(decisionsPath, "utf8"));
  } catch {
    return {};
  }
}

async function saveDecisions(decisions) {
  await mkdir(dataDir, { recursive: true });
  await writeFile(decisionsPath, JSON.stringify(decisions, null, 2) + "\n", "utf8");
}

// Serialize read-modify-write so overlapping autosaves (e.g. rapid bulk approval
// clicks) can't drop each other's changes.
let writeChain = Promise.resolve();
function withWriteLock(fn) {
  const run = writeChain.then(fn, fn);
  writeChain = run.then(() => {}, () => {});
  return run;
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function slug(value) {
  return String(value || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${host}:${port}`);

    if (req.method === "GET" && url.pathname === "/") {
      const html = await readFile(path.join(publicDir, "index.html"), "utf8");
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
      return res.end(html);
    }

    if (req.method === "GET" && url.pathname === "/api/bootstrap") {
      const dataset = await loadDataset();
      const decisions = await loadDecisions();
      return sendJson(res, {
        generated_at: dataset.generated_at,
        dev_ref: dataset.dev_ref,
        categories: dataset.categories,
        total: dataset.total,
        with_suggestion: dataset.with_suggestion,
        items: dataset.items,
        decisions,
        decisions_path: path.relative(repoRoot, decisionsPath),
      });
    }

    // Save one or many decisions. Body: { decisions: [{product_page_id, approved,
    // chosen_mother_category_id, is_new_category, clothing_type_id}] }
    if (req.method === "POST" && url.pathname === "/api/save") {
      const body = await readBody(req);
      const incoming = Array.isArray(body.decisions) ? body.decisions : [body];
      const result = await withWriteLock(async () => {
        const decisions = await loadDecisions();
        let saved = 0;
        for (const d of incoming) {
          if (!d.product_page_id) continue;
          // Mark a row for deletion (row + its images), handled by the apply script.
          if (d.decision === "remove") {
            decisions[d.product_page_id] = {
              product_page_id: d.product_page_id,
              decision: "remove",
              removed_at: new Date().toISOString(),
            };
            saved += 1;
            continue;
          }
          if (d.approved === false) {
            delete decisions[d.product_page_id];
            saved += 1;
            continue;
          }
          const chosen = d.chosen_mother_category_id ? slug(d.chosen_mother_category_id) : null;
          if (!chosen || chosen === "other") {
            // Approving with no real category is a no-op; skip silently.
            continue;
          }
          decisions[d.product_page_id] = {
            product_page_id: d.product_page_id,
            decision: "recategorize",
            chosen_mother_category_id: chosen,
            chosen_mother_category_label: d.chosen_mother_category_label || d.chosen_mother_category_id || null,
            is_new_category: Boolean(d.is_new_category),
            clothing_type_id: d.clothing_type_id || null,
            approved_at: new Date().toISOString(),
          };
          saved += 1;
        }
        await saveDecisions(decisions);
        return { saved, total: Object.keys(decisions).length };
      });
      return sendJson(res, { ok: true, saved: result.saved, total_decisions: result.total });
    }

    const filePath = path.join(publicDir, url.pathname.replace(/^\/+/, ""));
    if (req.method === "GET" && filePath.startsWith(publicDir) && existsSync(filePath)) {
      const ext = path.extname(filePath);
      res.writeHead(200, { "Content-Type": contentTypes.get(ext) || "application/octet-stream" });
      return res.end(await readFile(filePath));
    }

    return sendJson(res, { error: "not found" }, 404);
  } catch (error) {
    return sendJson(res, { error: String(error?.message || error) }, 500);
  }
});

const guard = await assertApprovedDevSupabase();
printGuardSummary(guard, { prefix: "other-category-review" });

server.listen(port, host, () => {
  console.log(`Other-category approval dashboard: http://${host}:${port}`);
  console.log(`Dataset:   ${path.relative(repoRoot, datasetPath)}`);
  console.log(`Decisions: ${path.relative(repoRoot, decisionsPath)} (saved into the repo, never Downloads)`);
  console.log(`No DB writes — apply later with: node scripts/apply-dev-other-category-approvals.mjs`);
});
