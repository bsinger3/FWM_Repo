#!/usr/bin/env node

// Lighting calibration dashboard. Renders dev images sorted by the model's lighting
// score, each with its sub-scores (exposure / brightness / contrast / cast) and the
// raw pixel measurements that drive them, plus a one-click label control so Bri can
// mark the TRUE lighting quality (bad / ok / good / great). Labels persist in the
// browser (localStorage) and export to a JSON file we feed back to recalibrate the
// thresholds in scripts/lib/lighting-score.mjs.
//
// Lighting is measured on the SAME frame the scorer uses: the post-autocrop card
// window when a crop_spec exists, else the full source. READ-ONLY: never writes
// Supabase. Usage:
//   node scripts/build-lighting-label-dashboard.mjs --source=workbook --limit=300

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { assertApprovedDevSupabase, callSupabaseRest, printGuardSummary } from "./lib/dev-supabase-guard.mjs";
import { cropWindowFractions } from "./lib/card-crop-geometry.mjs";
import { computePixelStats } from "./lib/pixel-stats.mjs";
import { lightingBreakdown, LIGHTING_WEIGHTS } from "./lib/lighting-score.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const limit = Math.max(1, Number(parseArg("limit", "300")) || 300);
const timeoutMs = Math.max(1000, Number(parseArg("timeout-ms", "12000")) || 12000);
const sourceFilter = parseArg("source", "workbook"); // all | workbook | baseline
const concurrency = Math.max(1, Number(parseArg("concurrency", "8")) || 8);

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function round(value, digits = 4) {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

function parseCropSpec(value) {
  if (!value) return null;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

async function runPool(items, worker, n, onProgress) {
  let next = 0;
  let done = 0;
  async function lane() {
    while (next < items.length) {
      const item = items[next++];
      await worker(item);
      done += 1;
      if (onProgress && done % 25 === 0) onProgress(done);
    }
  }
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, lane));
}

async function fetchCandidateRows(guard) {
  const searchParams = {
    select: "id,original_url_display,crop_spec,source_file",
    original_url_display: "not.is.null",
    order: "id",
    limit: String(limit),
  };
  if (sourceFilter === "workbook") searchParams.source_file = "neq.production_baseline_pg_dump";
  else if (sourceFilter === "baseline") searchParams.source_file = "eq.production_baseline_pg_dump";
  const { data } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "images",
    method: "GET",
    searchParams,
  });
  return Array.isArray(data) ? data : [];
}

async function fetchImage(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      redirect: "follow",
      headers: { "User-Agent": "FWMLightingLabeler/0.1 (+https://friendswithmeasurements.com)" },
    });
    const buf = Buffer.from(await res.arrayBuffer());
    return { ok: res.ok, status: res.status, bytes: buf };
  } finally {
    clearTimeout(timer);
  }
}

async function measure(row) {
  try {
    const fetched = await fetchImage(row.original_url_display);
    if (!fetched.ok) return { id: row.id, url: row.original_url_display, skipped: true, reason: `http_${fetched.status}` };
    const meta = await sharp(fetched.bytes).metadata();
    const W = meta.width;
    const H = meta.height;
    if (!W || !H) return { id: row.id, url: row.original_url_display, skipped: true, reason: "no_dimensions" };
    const cropSpec = parseCropSpec(row.crop_spec);
    const cropWindow = cropSpec ? cropWindowFractions(W, H, cropSpec) : null;
    const scoreOnCard = Boolean(cropWindow && cropWindow.mode !== "centered-cover");
    const stats = await computePixelStats(fetched.bytes, scoreOnCard ? { crop: cropWindow } : {});
    const b = lightingBreakdown(stats);
    return {
      id: row.id,
      url: row.original_url_display,
      source_file: row.source_file || null,
      skipped: false,
      scored_on_card: scoreOnCard,
      crop_window: scoreOnCard ? cropWindow : null,
      width: W,
      height: H,
      lighting: round(b.lighting),
      sub: {
        exposure: round(b.exposure),
        brightness: round(b.brightness),
        contrast: round(b.contrast),
        cast: round(b.cast),
      },
      raw: {
        mean_luma: round(b.raw.mean_luma, 1),
        contrast_std: round(b.raw.contrast_std, 1),
        color_cast: round(b.raw.color_cast, 3),
        clipped_shadow_pct: round(b.raw.clipped_shadow_frac * 100, 2),
        clipped_highlight_pct: round(b.raw.clipped_highlight_frac * 100, 2),
      },
    };
  } catch (error) {
    return { id: row.id, url: row.original_url_display, skipped: true, reason: String(error?.message || error) };
  }
}

function htmlEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// Position the source image so the card window fills the 3:4 frame; else cover.
function frameImg(r) {
  const w = r.crop_window;
  if (w && w.widthFrac && w.heightFrac) {
    const widthPct = (100 / w.widthFrac).toFixed(2);
    const heightPct = (100 / w.heightFrac).toFixed(2);
    const leftPct = (-(w.leftFrac / w.widthFrac) * 100).toFixed(2);
    const topPct = (-(w.topFrac / w.heightFrac) * 100).toFixed(2);
    return `<img class="win" src="${htmlEscape(r.url)}" loading="lazy" style="width:${widthPct}%;height:${heightPct}%;left:${leftPct}%;top:${topPct}%;">`;
  }
  return `<img src="${htmlEscape(r.url)}" loading="lazy">`;
}

function card(r) {
  const s = r.sub;
  const raw = r.raw;
  return `
  <article class="card" data-id="${htmlEscape(r.id)}" data-lighting="${r.lighting ?? 0}" data-luma="${raw.mean_luma ?? 0}">
    <div class="frame">${frameImg(r)}</div>
    <div class="body">
      <div class="big">light <b>${r.lighting ?? "—"}</b></div>
      <div class="subs">exp ${s.exposure} &middot; bright ${s.brightness} &middot; contrast ${s.contrast} &middot; cast ${s.cast}</div>
      <div class="raw">luma ${raw.mean_luma} &middot; std ${raw.contrast_std} &middot; cast ${raw.color_cast}<br>clip ${raw.clipped_shadow_pct}%/${raw.clipped_highlight_pct}% (lo/hi)</div>
      <div class="label" role="group" aria-label="true lighting quality">
        <button data-v="bad">bad</button>
        <button data-v="ok">ok</button>
        <button data-v="good">good</button>
        <button data-v="great">great</button>
      </div>
    </div>
  </article>`;
}

function buildHtml(report) {
  const rows = report.results.filter((r) => !r.skipped);
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>FWM Lighting Calibration (${rows.length} images)</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 20px; color: #1f2933; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .hint { color: #52606d; font-size: 13px; margin: 0 0 14px; max-width: 70ch; }
  .bar { position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid #d9e2ec;
    padding: 10px 0; margin-bottom: 16px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
  .bar label { font-size: 13px; color: #52606d; }
  .bar .count { font-weight: 700; }
  button { font: inherit; padding: 5px 10px; border: 1px solid #bcccdc; background: #fff; border-radius: 6px; cursor: pointer; }
  button.primary { background: #2b6cb0; color: #fff; border-color: #2b6cb0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; }
  .card { border: 1px solid #d9e2ec; border-radius: 8px; overflow: hidden; background: #fff; }
  .card.labeled { outline: 3px solid #2f855a; outline-offset: -3px; }
  .card.hidden { display: none; }
  .frame { position: relative; aspect-ratio: 3 / 4; overflow: hidden; background: #f0f4f8; }
  .frame img { width: 100%; height: 100%; object-fit: cover; }
  .frame img.win { position: absolute; max-width: none; object-fit: fill; }
  .body { padding: 6px 8px 8px; }
  .big { font-size: 15px; } .big b { font-size: 18px; }
  .subs { font-size: 11px; color: #52606d; margin-top: 2px; }
  .raw { font-size: 11px; color: #9aa5b1; margin-top: 2px; line-height: 1.4; }
  .label { display: flex; gap: 4px; margin-top: 8px; }
  .label button { flex: 1; padding: 4px 0; font-size: 12px; }
  .label button.sel { background: #2f855a; color: #fff; border-color: #2f855a; }
</style>
</head>
<body>
  <h1>Lighting calibration &mdash; label the TRUE lighting quality</h1>
  <p class="hint">Each card shows the model's lighting score, its sub-scores, and the raw pixel stats. Click bad / ok / good / great for what the lighting actually looks like (or hover a card and press 1&ndash;4). Sort by model score to find disagreements. Labels save in your browser automatically. When done, click <b>Save to _reports</b> &mdash; it writes your labels straight into <code>FWM_Data/_reports/</code> where Claude reads them (no Downloads detour, when served by scripts/lighting-label-server.mjs). <b>Copy JSON</b> (paste to Claude) and <b>Download JSON</b> are fallbacks. Then I refit the thresholds.</p>
  <div class="bar">
    <span><span class="count" id="done">0</span> / ${rows.length} labeled</span>
    <label>sort <select id="sort">
      <option value="light_desc">model lighting ↓ (find false-highs)</option>
      <option value="light_asc">model lighting ↑ (find false-lows)</option>
      <option value="luma_desc">mean luma ↓</option>
      <option value="luma_asc">mean luma ↑</option>
    </select></label>
    <label><input type="checkbox" id="unlabeled"> unlabeled only</label>
    <button id="save" class="primary">Save to _reports</button>
    <button id="export">Download JSON</button>
    <button id="copy">Copy JSON</button>
    <button id="clear">Clear all</button>
  </div>
  <div class="grid" id="grid">${rows.map(card).join("")}</div>
  <script id="data" type="application/json">${JSON.stringify(
    report.results.filter((r) => !r.skipped).map((r) => ({
      id: r.id,
      url: r.url,
      lighting: r.lighting,
      sub: r.sub,
      raw: r.raw,
      scored_on_card: r.scored_on_card,
    })),
  )}</script>
  <script>
  (function () {
    var KEY = "fwm_lighting_labels_v1";
    var TARGET = { bad: 0.2, ok: 0.55, good: 0.78, great: 0.93 };
    var labels = {};
    try { labels = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { labels = {}; }
    var grid = document.getElementById("grid");
    var cards = Array.prototype.slice.call(grid.querySelectorAll(".card"));
    var hovered = null;

    function refresh(c) {
      var id = c.getAttribute("data-id");
      var v = labels[id] || null;
      c.classList.toggle("labeled", !!v);
      c.querySelectorAll(".label button").forEach(function (b) {
        b.classList.toggle("sel", b.getAttribute("data-v") === v);
      });
    }
    function setLabel(c, v) {
      var id = c.getAttribute("data-id");
      if (labels[id] === v) { delete labels[id]; } else { labels[id] = v; }
      localStorage.setItem(KEY, JSON.stringify(labels));
      refresh(c);
      updateCount();
      applyFilter();
    }
    function updateCount() { document.getElementById("done").textContent = Object.keys(labels).length; }
    function applyFilter() {
      var only = document.getElementById("unlabeled").checked;
      cards.forEach(function (c) {
        var labeled = !!labels[c.getAttribute("data-id")];
        c.classList.toggle("hidden", only && labeled);
      });
    }
    function sortCards() {
      var mode = document.getElementById("sort").value;
      var arr = cards.slice();
      arr.sort(function (a, b) {
        var al = parseFloat(a.getAttribute("data-lighting")), bl = parseFloat(b.getAttribute("data-lighting"));
        var au = parseFloat(a.getAttribute("data-luma")), bu = parseFloat(b.getAttribute("data-luma"));
        if (mode === "light_desc") return bl - al;
        if (mode === "light_asc") return al - bl;
        if (mode === "luma_desc") return bu - au;
        return au - bu;
      });
      arr.forEach(function (c) { grid.appendChild(c); });
    }

    cards.forEach(function (c) {
      refresh(c);
      c.addEventListener("mouseenter", function () { hovered = c; });
      c.querySelectorAll(".label button").forEach(function (b) {
        b.addEventListener("click", function () { setLabel(c, b.getAttribute("data-v")); });
      });
    });
    document.addEventListener("keydown", function (e) {
      if (!hovered) return;
      var map = { "1": "bad", "2": "ok", "3": "good", "4": "great" };
      if (map[e.key]) { setLabel(hovered, map[e.key]); }
    });
    document.getElementById("sort").addEventListener("change", sortCards);
    document.getElementById("unlabeled").addEventListener("change", applyFilter);
    document.getElementById("clear").addEventListener("click", function () {
      if (!confirm("Clear all lighting labels?")) return;
      labels = {}; localStorage.setItem(KEY, JSON.stringify(labels));
      cards.forEach(refresh); updateCount(); applyFilter();
    });

    function buildExport() {
      var data = JSON.parse(document.getElementById("data").textContent);
      var byId = {}; data.forEach(function (d) { byId[d.id] = d; });
      var out = { exported_at: new Date().toISOString(), label_count: Object.keys(labels).length,
        target_bands: TARGET, labels: [] };
      Object.keys(labels).forEach(function (id) {
        var d = byId[id] || {};
        out.labels.push({ id: id, url: d.url, human_label: labels[id], human_target: TARGET[labels[id]],
          model_lighting: d.lighting, model_sub: d.sub, raw: d.raw });
      });
      return JSON.stringify(out, null, 2);
    }
    document.getElementById("save").addEventListener("click", function () {
      if (!Object.keys(labels).length) { alert("No labels yet."); return; }
      var btn = this; btn.disabled = true; btn.textContent = "Saving…";
      fetch("/save-labels", { method: "POST", headers: { "Content-Type": "application/json" }, body: buildExport() })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          btn.disabled = false; btn.textContent = "Save to _reports";
          if (j.ok) { alert("Saved " + (j.count != null ? j.count + " " : "") + "labels to:\\n" + j.path + "\\n\\nTell Claude it's saved — it can read that folder."); }
          else { alert("Save failed: " + j.error + "\\nUse Download JSON or Copy JSON instead."); }
        })
        .catch(function (e) {
          btn.disabled = false; btn.textContent = "Save to _reports";
          alert("Save server not reachable (" + e.message + ").\\nThis button needs the page served by scripts/lighting-label-server.mjs. Use Download JSON or Copy JSON instead.");
        });
    });
    document.getElementById("export").addEventListener("click", function () {
      var blob = new Blob([buildExport()], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "lighting_labels_" + new Date().toISOString().replace(/[:.]/g, "-") + ".json";
      a.click();
    });
    document.getElementById("copy").addEventListener("click", function () {
      navigator.clipboard.writeText(buildExport()).then(function () { alert("Copied " + Object.keys(labels).length + " labels to clipboard."); });
    });

    updateCount(); sortCards(); applyFilter();
  })();
  </script>
</body>
</html>
`;
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Lighting dashboard guard" });

  const rows = await fetchCandidateRows(guard);
  console.log(`Fetched ${rows.length} candidate rows (source=${sourceFilter}). Measuring lighting (concurrency ${concurrency})...`);
  const results = [];
  await runPool(rows, async (row) => results.push(await measure(row)), concurrency, (n) =>
    console.log(`  measured ${n}/${rows.length}`),
  );

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const stem = `dev_lighting_calibration_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const report = {
    generated_at: generatedAt,
    mode: "read-only",
    supabase_project_ref: guard.projectRef,
    source_filter: sourceFilter,
    lighting_weights: LIGHTING_WEIGHTS,
    limit,
    counts: { fetched: rows.length, measured: results.filter((r) => !r.skipped).length, skipped: results.filter((r) => r.skipped).length },
    results,
  };
  const jsonPath = path.join(reportsDir, `${stem}.json`);
  const htmlPath = path.join(reportsDir, `${stem}.html`);
  await writeFile(jsonPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  await writeFile(htmlPath, buildHtml(report), "utf8");

  const scored = results.filter((r) => !r.skipped);
  const ls = scored.map((r) => r.lighting).filter((v) => v != null).sort((a, b) => a - b);
  console.log(`Wrote lighting calibration report: ${jsonPath}`);
  console.log(`Wrote lighting label dashboard:    ${htmlPath}`);
  console.log(`Measured ${scored.length}, skipped ${results.length - scored.length}.`);
  if (ls.length) console.log(`Lighting score: min ${ls[0]} median ${ls[Math.floor(ls.length / 2)]} max ${ls[ls.length - 1]}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
