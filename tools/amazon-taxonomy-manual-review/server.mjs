#!/usr/bin/env node
/**
 * Manual review dashboard for the Amazon taxonomy backfill's PROBLEM rows — the
 * pages the automated pass could not confidently categorize:
 *   - "ambiguous"        : fetched OK but two categories tied (no primary)
 *   - "captcha_or_block" : Amazon throttled it past max retries
 *   - "http_status_404"  : dead page
 *
 * It lists each page with a click-to-open Amazon link and DESCRIPTIVE,
 * STRUCTURED inputs (taxonomy dropdowns sourced from clothing-taxonomy.json,
 * not free text) so a human can fill in the real category. Every change is
 * saved straight into the repo (no browser download):
 *   data-pipelines/products/manual_taxonomy_review/amazon_manual_taxonomy_decisions.{ndjson,json}
 *
 * Read-only against the backfill: it only READS the progress sidecar (the live
 * backfill keeps appending to it), so running this never disturbs the run.
 *
 * Usage:  node tools/amazon-taxonomy-manual-review/server.mjs
 *         PORT=4176 node tools/amazon-taxonomy-manual-review/server.mjs
 */

import { createServer } from "node:http";
import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fwmDataDir } from "../image-review-dashboard/paths.mjs";
import { extractTaxonomy } from "../../scripts/audit-dev-product-page-taxonomy.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = Number(process.env.PORT) || 4176;
const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
const taxonomyPath = path.join(repoRoot, "data-pipelines/products/taxonomy/clothing-taxonomy.json");
const outputDir = path.join(repoRoot, "data-pipelines/products/manual_taxonomy_review");
const outputNdjson = path.join(outputDir, "amazon_manual_taxonomy_decisions.ndjson");
const outputJson = path.join(outputDir, "amazon_manual_taxonomy_decisions.json");

const PROBLEM_BUCKETS = ["ambiguous", "captcha_or_block", "http_status_404"];

// ---- data loading -----------------------------------------------------------

function latestProgressSidecar() {
  const files = readdirSyncSafe(reportsDir)
    .filter((f) => /^amazon_taxonomy_worklist_.*_progress\.ndjson$/.test(f))
    .sort();
  if (!files.length) throw new Error(`No *_progress.ndjson in ${reportsDir}`);
  return path.join(reportsDir, files[files.length - 1]);
}
function readdirSyncSafe(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

async function loadProblemRows() {
  const sidecar = latestProgressSidecar();
  const raw = await readFile(sidecar, "utf8");
  const rows = [];
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    let r;
    try {
      r = JSON.parse(line);
    } catch {
      continue;
    }
    const f = r.extracted_fields_preview || {};
    let bucket = null;
    if (r.skipped) {
      if (r.skip_reason === "captcha_or_block") bucket = "captcha_or_block";
      else if (r.skip_reason === "http_status_404") bucket = "http_status_404";
    } else if (!r.proposed?.primaryCategory?.mother_category_id) {
      // Re-classify with the CURRENT extractTaxonomy (which now has the breadcrumb
      // tie-break). Rows the live backfill recorded as ambiguous under the old code
      // may now resolve — those drop out of the manual queue and flow through the
      // normal promote pipeline. Only genuinely-still-ambiguous rows stay here.
      const reFields = {
        title: f.title || "",
        breadcrumb: r.breadcrumb_path || f.breadcrumb || "",
        description: f.description || "",
        url_slug: f.url_slug || "",
        json_ld_product_core: "",
        json_ld_product_description: "",
        workbook_fallback: "",
      };
      if (!extractTaxonomy(reFields).primaryCategory?.mother_category_id) bucket = "ambiguous";
    }
    if (!bucket) continue;
    rows.push({
      product_page_id: r.product_page_id,
      asin: r.asin,
      canonical_url: r.canonical_url,
      normalized_product_page_url: r.normalized_product_page_url,
      bucket,
      title: f.title || "",
      breadcrumb: r.breadcrumb_path || f.breadcrumb || "",
      bsr: f.description || "",
      competing: (r.proposed?.categoryVotes || [])
        .slice(0, 4)
        .map((v) => `${v.mother_category_id} (${v.evidence_tag})`)
        .join("  ·  "),
    });
  }
  return { rows, sidecar: path.basename(sidecar) };
}

function loadTaxonomy() {
  const t = JSON.parse(readFileSync(taxonomyPath, "utf8"));
  const categories = (t.mother_categories || []).map((m) => ({ id: m.id, label: m.label, description: m.description || "" }));
  const tags = (t.category_tags || []).map((c) => ({ id: c.id, mother_category_id: c.mother_category_id }));
  return { categories, tags };
}

async function loadDecisions() {
  const map = {};
  if (!existsSync(outputNdjson)) return map;
  const raw = await readFile(outputNdjson, "utf8");
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    try {
      const d = JSON.parse(line);
      if (d.product_page_id) map[d.product_page_id] = d;
    } catch {
      /* skip */
    }
  }
  return map;
}

const decisions = await loadDecisions();

async function persistDecisions() {
  await mkdir(outputDir, { recursive: true });
  const list = Object.values(decisions).sort((a, b) => (a.decided_at < b.decided_at ? 1 : -1));
  await writeFile(outputNdjson, list.map((d) => JSON.stringify(d)).join("\n") + (list.length ? "\n" : ""), "utf8");
  await writeFile(outputJson, JSON.stringify({ updated_at: new Date().toISOString(), count: list.length, decisions: list }, null, 2) + "\n", "utf8");
}

// ---- http -------------------------------------------------------------------

function send(res, status, body, type = "application/json") {
  res.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store" });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return Buffer.concat(chunks).toString("utf8");
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    if (req.method === "GET" && url.pathname === "/") {
      return send(res, 200, PAGE_HTML, "text/html; charset=utf-8");
    }
    if (req.method === "GET" && url.pathname === "/api/bootstrap") {
      const { rows, sidecar } = await loadProblemRows();
      const { categories, tags } = loadTaxonomy();
      const counts = { ambiguous: 0, captcha_or_block: 0, http_status_404: 0 };
      for (const r of rows) counts[r.bucket]++;
      return send(res, 200, {
        rows,
        categories,
        tags,
        decisions,
        counts,
        total: rows.length,
        decided: rows.filter((r) => decisions[r.product_page_id]).length,
        sidecar,
        output_path: path.relative(repoRoot, outputNdjson),
      });
    }
    if (req.method === "POST" && url.pathname === "/api/save") {
      const body = JSON.parse((await readBody(req)) || "{}");
      if (!body.product_page_id) return send(res, 400, { ok: false, error: "missing product_page_id" });
      decisions[body.product_page_id] = { ...body, decided_at: new Date().toISOString() };
      await persistDecisions();
      return send(res, 200, { ok: true, decided: Object.keys(decisions).length });
    }
    if (req.method === "POST" && url.pathname === "/api/delete") {
      const body = JSON.parse((await readBody(req)) || "{}");
      delete decisions[body.product_page_id];
      await persistDecisions();
      return send(res, 200, { ok: true, decided: Object.keys(decisions).length });
    }
    return send(res, 404, { error: "not found" });
  } catch (error) {
    return send(res, 500, { error: String(error?.message || error) });
  }
});

server.listen(PORT, () => {
  console.log(`Amazon taxonomy manual-review dashboard: http://localhost:${PORT}`);
  console.log(`Reading problem rows from the latest *_progress.ndjson in ${reportsDir}`);
  console.log(`Saving decisions into the repo: ${path.relative(repoRoot, outputNdjson)}`);
});

// ---- page -------------------------------------------------------------------

const PAGE_HTML = /* html */ `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon taxonomy — manual review</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font: 14px/1.4 -apple-system, system-ui, sans-serif; margin: 0; background: #f4f5f7; color: #1a1a1a; }
  header { position: sticky; top: 0; z-index: 10; background: #111827; color: #fff; padding: 10px 16px; box-shadow: 0 1px 4px rgba(0,0,0,.25); }
  header h1 { font-size: 15px; margin: 0 0 6px; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 12px; }
  .bar button { font: inherit; padding: 4px 10px; border-radius: 6px; border: 1px solid #374151; background: #1f2937; color: #d1d5db; cursor: pointer; }
  .bar button.active { background: #2563eb; border-color: #2563eb; color: #fff; }
  .bar .stat { background: #0b1220; padding: 4px 10px; border-radius: 6px; }
  .bar .out { color: #9ca3af; margin-left: auto; font-family: ui-monospace, monospace; }
  main { padding: 16px; max-width: 1000px; margin: 0 auto; display: grid; gap: 14px; }
  .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
  .card.done { border-left: 5px solid #16a34a; }
  .card .top { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
  .badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; text-transform: uppercase; letter-spacing: .03em; }
  .b-ambiguous { background: #fef3c7; color: #92400e; }
  .b-captcha_or_block { background: #fee2e2; color: #991b1b; }
  .b-http_status_404 { background: #e5e7eb; color: #374151; }
  .asin { font-family: ui-monospace, monospace; color: #6b7280; }
  .open { margin-left: auto; font-weight: 600; text-decoration: none; background: #2563eb; color: #fff; padding: 6px 12px; border-radius: 6px; }
  .open:hover { background: #1d4ed8; }
  .ctx { margin: 8px 0; font-size: 13px; color: #374151; }
  .ctx .lbl { color: #9ca3af; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
  .ctx .t { font-weight: 600; color: #111827; }
  .ctx .crumbs { font-family: ui-monospace, monospace; font-size: 12px; }
  .ctx .vote { color: #b45309; }
  form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 14px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed #e5e7eb; }
  .field { display: flex; flex-direction: column; gap: 3px; }
  .field.wide { grid-column: 1 / -1; }
  label { font-size: 11px; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: .03em; }
  select, input[type=text], textarea { font: inherit; padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px; background: #fff; }
  select[multiple] { min-height: 84px; }
  textarea { resize: vertical; min-height: 38px; }
  .saved { font-size: 11px; color: #16a34a; height: 14px; }
  .hint { font-size: 11px; color: #9ca3af; }
  .empty { text-align: center; color: #6b7280; padding: 40px; }
</style></head>
<body>
<header>
  <h1>Amazon taxonomy — manual review <span id="sidecar" class="hint"></span></h1>
  <div class="bar">
    <span class="stat" id="progress">…</span>
    <button data-f="all" class="active">All</button>
    <button data-f="ambiguous">Ambiguous</button>
    <button data-f="captcha_or_block">Blocked</button>
    <button data-f="http_status_404">404</button>
    <button data-f="undecided">Undecided</button>
    <button data-f="done">Done</button>
    <button id="refresh">↻ Refresh</button>
    <span class="out" id="out"></span>
  </div>
</header>
<main id="main"><div class="empty">Loading…</div></main>
<script>
let DATA = null, FILTER = "all";
const STATUSES = [
  ["valid_product", "Valid product — categorize below"],
  ["not_a_product", "Not a clothing product"],
  ["dead_link", "Dead / removed listing"],
  ["unavailable", "Unavailable / out of stock"],
  ["duplicate", "Duplicate of another page"],
];
const el = (t, props={}, kids=[]) => { const e = document.createElement(t); Object.assign(e, props); for (const k of [].concat(kids)) e.append(k); return e; };

async function boot() {
  DATA = await (await fetch("/api/bootstrap")).json();
  document.getElementById("sidecar").textContent = "· " + DATA.sidecar + " · saves to " + DATA.output_path;
  for (const b of document.querySelectorAll(".bar button[data-f]")) {
    b.onclick = () => { FILTER = b.dataset.f; for (const x of document.querySelectorAll(".bar button[data-f]")) x.classList.toggle("active", x===b); render(); };
  }
  document.getElementById("refresh").onclick = boot;
  render();
}

function render() {
  const main = document.getElementById("main");
  main.innerHTML = "";
  const decided = DATA.rows.filter(r => DATA.decisions[r.product_page_id]).length;
  document.getElementById("progress").textContent = decided + " / " + DATA.total + " decided  (amb " + DATA.counts.ambiguous + " · blocked " + DATA.counts.captcha_or_block + " · 404 " + DATA.counts.http_status_404 + ")";
  const rows = DATA.rows.filter(r => {
    const has = !!DATA.decisions[r.product_page_id];
    if (FILTER === "all") return true;
    if (FILTER === "undecided") return !has;
    if (FILTER === "done") return has;
    return r.bucket === FILTER;
  });
  if (!rows.length) { main.append(el("div", {className:"empty", textContent:"Nothing in this filter."})); return; }
  for (const r of rows) main.append(card(r));
}

function card(r) {
  const d = DATA.decisions[r.product_page_id] || {};
  const c = el("div", { className: "card" + (DATA.decisions[r.product_page_id] ? " done" : "") });
  const top = el("div", { className: "top" }, [
    el("span", { className: "badge b-" + r.bucket, textContent: r.bucket === "http_status_404" ? "404" : r.bucket === "captcha_or_block" ? "blocked" : "ambiguous" }),
    el("span", { className: "asin", textContent: r.asin }),
  ]);
  const open = el("a", { className: "open", href: r.canonical_url, target: "_blank", rel: "noopener", textContent: "Open on Amazon ↗" });
  top.append(open);
  c.append(top);

  const ctx = el("div", { className: "ctx" });
  if (r.title) ctx.append(el("div", {}, [el("span",{className:"lbl",textContent:"title "}), el("span",{className:"t",textContent:r.title})]));
  if (r.breadcrumb) ctx.append(el("div", { className:"crumbs" }, [el("span",{className:"lbl",textContent:"breadcrumb "}), document.createTextNode(r.breadcrumb)]));
  if (r.bsr) ctx.append(el("div", { className:"crumbs" }, [el("span",{className:"lbl",textContent:"best sellers "}), document.createTextNode(r.bsr)]));
  if (r.competing) ctx.append(el("div", {}, [el("span",{className:"lbl",textContent:"tied options "}), el("span",{className:"vote",textContent:r.competing})]));
  if (!r.title && !r.breadcrumb) ctx.append(el("div", { className:"hint", textContent:"No data captured (page was skipped) — open the link to inspect." }));
  c.append(ctx);

  // form
  const form = el("form");
  const saved = el("div", { className: "saved" });

  const statusSel = el("select");
  for (const [v,l] of STATUSES) statusSel.append(el("option",{value:v,textContent:l,selected:(d.status||"valid_product")===v}));
  const catSel = el("select");
  catSel.append(el("option",{value:"",textContent:"— pick category —"}));
  for (const cat of DATA.categories) catSel.append(el("option",{value:cat.id,textContent:cat.label+" ("+cat.id+")",selected:d.mother_category_id===cat.id}));
  const typeSel = el("select", { multiple: true });
  const fillTypes = () => {
    typeSel.innerHTML = "";
    const mc = catSel.value;
    const tags = DATA.tags.filter(t => !mc || t.mother_category_id === mc);
    const chosen = new Set(d.clothing_type_ids || []);
    for (const t of tags) typeSel.append(el("option",{value:t.id,textContent:t.id,selected:chosen.has(t.id)}));
    if (!tags.length) typeSel.append(el("option",{value:"",textContent:"(pick a category first)",disabled:true}));
  };
  fillTypes();
  catSel.onchange = () => { fillTypes(); save(); };

  const crumbInput = el("input", { type:"text", value: d.breadcrumb_path != null ? d.breadcrumb_path : (r.breadcrumb||"") , placeholder:"Full breadcrumb path, e.g. Clothing, Shoes & Jewelry > Women > Clothing > Jeans" });
  const confSel = el("select");
  for (const v of ["high","medium","low"]) confSel.append(el("option",{value:v,textContent:v,selected:(d.confidence||"high")===v}));
  const notes = el("textarea", { value: d.notes || "", placeholder:"Optional notes" });

  const mk = (lbl, node, wide) => el("div",{className:"field"+(wide?" wide":"")},[el("label",{textContent:lbl}), node]);
  form.append(
    mk("Status", statusSel),
    mk("Mother category", catSel),
    mk("Clothing type(s) — ⌘/Ctrl-click for multiple", typeSel, true),
    mk("Full breadcrumb path", crumbInput, true),
    mk("Confidence", confSel),
    mk("Notes", notes),
  );
  c.append(form);
  c.append(saved);

  let timer = null;
  function save() {
    const payload = {
      product_page_id: r.product_page_id,
      asin: r.asin,
      canonical_url: r.canonical_url,
      normalized_product_page_url: r.normalized_product_page_url,
      bucket: r.bucket,
      status: statusSel.value,
      mother_category_id: catSel.value || null,
      clothing_type_ids: [...typeSel.selectedOptions].map(o => o.value).filter(Boolean),
      breadcrumb_path: crumbInput.value.trim() || null,
      confidence: confSel.value,
      notes: notes.value.trim() || null,
    };
    clearTimeout(timer);
    timer = setTimeout(async () => {
      saved.textContent = "saving…";
      const res = await (await fetch("/api/save", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload) })).json();
      DATA.decisions[r.product_page_id] = { ...payload, decided_at: new Date().toISOString() };
      c.classList.add("done");
      saved.textContent = "✓ saved to repo · " + res.decided + " total";
      document.getElementById("out").textContent = res.decided + " saved";
      const decided = DATA.rows.filter(x => DATA.decisions[x.product_page_id]).length;
      document.getElementById("progress").textContent = decided + " / " + DATA.total + " decided  (amb " + DATA.counts.ambiguous + " · blocked " + DATA.counts.captcha_or_block + " · 404 " + DATA.counts.http_status_404 + ")";
    }, 350);
  }
  for (const node of [statusSel, typeSel, crumbInput, confSel, notes]) node.addEventListener("change", save);
  notes.addEventListener("input", save);
  return c;
}
boot();
</script>
</body></html>`;
