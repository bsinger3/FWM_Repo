#!/usr/bin/env node

// Builds a before/after auto-crop review dashboard. For each detected image it
// runs the crop solver and renders, side by side:
//   - the ORIGINAL at native aspect, with the detected person box (green) and the
//     chosen crop window (red) overlaid, so you can see WHERE the crop lands;
//   - the AFTER 3:4 card, rendered exactly like the live site (object-fit: cover
//     + object-position + transform: scale(zoom)).
//
// Input: ndjson from scripts/detect_person_boxes.py. Output: HTML + JSON in
// ../FWM_Data/_reports/. Read-only; writes no Supabase rows.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { decideCrop } from "./lib/detection-crop.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArg(name, def = null) {
  const m = process.argv.find((a) => a.startsWith(`--${name}=`));
  return m ? m.slice(name.length + 3) : def;
}
const inputPath = parseArg("input", "/tmp/crop_bboxes.ndjson");
const catalogPath = parseArg("catalog", "/tmp/clothing_catalog.json");

function htmlEscape(v) {
  return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
function pct(v) {
  return (Math.max(0, Math.min(1, v)) * 100).toFixed(2) + "%";
}

const MODE_LABEL = {
  whole_body: '<span class="ok">whole body</span>',
  garment_priority: '<span class="warn">garment-priority</span>',
  garment_partial: '<span class="warn">garment-partial</span>',
  head_priority: '<span class="warn">head-priority</span>',
};

function card(item) {
  const { rec, person, crop, region, motherCategory, clothingType } = item;
  const c = crop.crop_spec;
  const e = crop.evidence;
  const win = e.window;
  // Render the explicit crop window: size the image so the window fills the card and
  // offset it to the window's top-left. No zoom cap, no centre-lock.
  const afterStyle =
    `position:absolute;max-width:none;` +
    `width:${(100 / win.width).toFixed(3)}%;height:${(100 / win.height).toFixed(3)}%;` +
    `left:${(-(win.left / win.width) * 100).toFixed(3)}%;top:${(-(win.top / win.height) * 100).toFixed(3)}%;`;
  const bandOverlay = region
    ? `<div class="box band" style="left:${pct(person.left)};top:${pct(region.top)};width:${pct(person.width)};height:${pct(region.bottom - region.top)}"></div>`
    : "";
  const cat = `${htmlEscape(clothingType || "?")}${motherCategory ? " / " + htmlEscape(motherCategory) : ""}`;
  const garment = e.garment_retained != null ? ` &middot; garmentKeep ${e.garment_retained} (${htmlEscape(region?.label || "")})` : "";
  return `
    <article class="card ${e.mode === "whole_body" ? "" : "capped"}">
      <div class="panels">
        <figure>
          <div class="orig" style="aspect-ratio:${rec.img_width} / ${rec.img_height}">
            <img src="${htmlEscape(rec.url)}" loading="lazy">
            <div class="box person" style="left:${pct(person.left)};top:${pct(person.top)};width:${pct(person.width)};height:${pct(person.height)}"></div>
            ${bandOverlay}
            <div class="box window" style="left:${pct(win.left)};top:${pct(win.top)};width:${pct(win.width)};height:${pct(win.height)}"></div>
          </div>
          <figcaption>original ${rec.img_width}&times;${rec.img_height} &middot; green=person blue=garment red=crop</figcaption>
        </figure>
        <figure>
          <div class="after"><img src="${htmlEscape(rec.url)}" style="${afterStyle}" loading="lazy"></div>
          <figcaption>auto-crop result (3:4 card)</figcaption>
        </figure>
      </div>
      <div class="meta">
        ${MODE_LABEL[e.mode] || e.mode} &middot; <b>${cat}</b> &middot; keepH ${e.retained_height} &middot; cardCov ${e.card_coverage}${garment}<br>
        zoom ${c.zoom} &middot; posX ${c.objectPositionXPct} posY ${c.objectPositionYPct}
      </div>
    </article>`;
}

function buildHtml(items, summary, generatedAt) {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>FWM Auto-Crop Review</title>
<style>
  body{font-family:system-ui,sans-serif;margin:24px;color:#1f2933;background:#fafbfc}
  header{margin-bottom:16px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
  .card{border:1px solid #d9e2ec;border-radius:8px;background:#fff;padding:10px}
  .card.capped{border-color:#f0b429;background:#fffaf0}
  .panels{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .orig{position:relative;width:100%;background:#f0f4f8;overflow:hidden}
  .orig img{width:100%;height:100%;object-fit:fill;display:block}
  .box{position:absolute;box-sizing:border-box}
  .box.person{border:2px solid #19a974}
  .box.band{border:2px dashed #2186eb;background:rgba(33,134,235,.12)}
  .box.window{border:2px solid #e0245e}
  .after{position:relative;aspect-ratio:3 / 4;overflow:hidden;background:#f0f4f8}
  figcaption{font-size:11px;color:#52606d;margin-top:4px}
  .meta{font-size:12px;color:#3e4c59;margin-top:8px}
  .ok{color:#19a974;font-weight:600}.warn{color:#cb6e17;font-weight:600}
  pre{white-space:pre-wrap;font-size:11px;background:#f8fafc;padding:8px;border-radius:6px}
</style></head><body>
<header>
  <h1>FWM Auto-Crop Review</h1>
  <p>Generated ${htmlEscape(generatedAt)}. Sorted worst body-retention first. Green = detected person; blue dashed = garment region from taxonomy (kept when the whole body can't fit); red = chosen crop window.</p>
  <pre>${htmlEscape(JSON.stringify(summary, null, 2))}</pre>
</header>
<main class="grid">${items.map(card).join("")}</main>
</body></html>`;
}

async function main() {
  const raw = await readFile(inputPath, "utf8");
  const recs = raw.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => JSON.parse(l));
  let catalog = {};
  try {
    catalog = JSON.parse(await readFile(catalogPath, "utf8"));
  } catch {
    console.warn(`No clothing catalog at ${catalogPath}; garment regions will fall back to head-priority.`);
  }
  const items = [];
  let noPerson = 0;
  let errored = 0;
  for (const rec of recs) {
    const decision = decideCrop(rec, { catalog });
    if (decision.skip) {
      if (decision.skip === "fetch_error") errored += 1;
      else noPerson += 1;
      continue;
    }
    const { person, crop, region, motherCategory, clothingType } = decision;
    items.push({ rec, person, crop, region, motherCategory, clothingType });
  }
  // Show the riskiest crops first: garment-priority / head-priority (body didn't
  // fully fit), then by least body retained.
  items.sort((a, b) => a.crop.evidence.retained_height - b.crop.evidence.retained_height);

  const byMode = {};
  for (const i of items) byMode[i.crop.evidence.mode] = (byMode[i.crop.evidence.mode] || 0) + 1;
  const summary = {
    input: inputPath,
    detections: recs.length,
    cropped: items.length,
    no_person: noPerson,
    fetch_errors: errored,
    by_mode: byMode,
    zoomed_in: items.filter((i) => i.crop.crop_spec.zoom > 1.001).length,
  };

  const generatedAt = new Date().toISOString();
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const stem = `dev_auto_crop_dashboard_${generatedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}`;
  const htmlPath = path.join(reportsDir, `${stem}.html`);
  const jsonPath = path.join(reportsDir, `${stem}.json`);
  await writeFile(htmlPath, buildHtml(items, summary, generatedAt), "utf8");
  await writeFile(
    jsonPath,
    JSON.stringify({ generated_at: generatedAt, summary, items: items.map((i) => ({ id: i.rec.id, url: i.rec.url, crop_spec: i.crop.crop_spec, evidence: i.crop.evidence })) }, null, 2) + "\n",
    "utf8",
  );
  console.log(`Wrote auto-crop dashboard: ${htmlPath}`);
  console.log(`Summary: ${JSON.stringify(summary)}`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
