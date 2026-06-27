#!/usr/bin/env node

// Builds a smile-validation gallery from the face/smile detector output
// (scripts/detect_faces_smiles.py -> face_smile_full.ndjson). Each card shows the
// face cropped in, its FER+ smile score, and a smiling / not / mouth-covered label,
// with a min-smile-score slider. Read-only; writes an HTML file under _reports.
//
//   node scripts/build-smile-validation-dashboard.mjs \
//     --input ../FWM_Data/_cache/face_smile_full.ndjson --cap 600

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArg(name, def = null) {
  const m = process.argv.find((a) => a.startsWith(`--${name}=`));
  if (m) return m.slice(name.length + 3);
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : def;
}

const inputPath = parseArg("input", path.join(fwmDataDir(repoRoot), "_cache", "face_smile_full.ndjson"));
const cap = Math.max(50, Number(parseArg("cap", "600")) || 600);

function htmlEscape(v) {
  return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

// Source-px face box -> CSS transform that zooms an expanded square face box to
// fill a square frame (same model as the prettiness card framing).
function framing(r) {
  const [x1, y1, x2, y2] = r.face_box_xyxy;
  const W = r.img_w;
  const H = r.img_h;
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  const side = Math.max(x2 - x1, y2 - y1) * 1.7;
  const bx = cx - side / 2;
  const by = cy - side / 2;
  return {
    wPct: +((W / side) * 100).toFixed(1),
    hPct: +((H / side) * 100).toFixed(1),
    lPct: +((-bx / side) * 100).toFixed(1),
    tPct: +((-by / side) * 100).toFixed(1),
  };
}

function card(r) {
  const f = framing(r);
  const s = Number.isFinite(r.smile_score) ? r.smile_score : 0;
  const col = r.mouth_occluded ? "#a32d2d" : r.smile ? "#1d9e75" : "#5f5e5a";
  const badge = r.mouth_occluded ? "mouth covered" : r.smile ? "smiling" : "not";
  return `<div class="card" data-smile="${s}"><div class="frame"><img loading="lazy" src="${htmlEscape(r.url)}" style="width:${f.wPct}%;height:${f.hPct}%;left:${f.lPct}%;top:${f.tPct}%"></div>` +
    `<div class="bar"><span class="score" style="color:${col}">${s.toFixed(2)}</span> <span class="b" style="background:${col}">${badge}</span> <span class="conf">face ${(r.face_conf ?? 0).toFixed(2)}</span></div></div>`;
}

async function main() {
  const raw = await readFile(inputPath, "utf8");
  const faces = [];
  for (const line of raw.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    let r;
    try {
      r = JSON.parse(t);
    } catch {
      continue;
    }
    if (r.has_face && Array.isArray(r.face_box_xyxy)) faces.push(r);
  }
  faces.sort((a, b) => (b.smile_score ?? 0) - (a.smile_score ?? 0));
  // Evenly sample across the score-sorted list so the gallery spans 1.0 -> 0.0.
  let shown = faces;
  if (faces.length > cap) {
    const step = faces.length / cap;
    shown = Array.from({ length: cap }, (_, i) => faces[Math.floor(i * step)]);
  }
  const smiling = shown.filter((r) => r.smile && !r.mouth_occluded).length;
  const covered = shown.filter((r) => r.mouth_occluded).length;

  const html = `<!doctype html><meta charset="utf-8"><title>Smile validation (YuNet + FER+)</title>
<style>
body{font-family:system-ui,sans-serif;margin:24px;color:#1f2933}h1{font-size:20px}p{color:#52606d;font-size:14px}
.bar-top{position:sticky;top:0;background:#fff;border-bottom:1px solid #d9e2ec;padding:12px 0;margin-bottom:16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;z-index:5}
.bar-top input[type=range]{flex:1;min-width:240px;max-width:480px}.thr{font-weight:700;min-width:3em}
.legend{display:flex;gap:14px;font-size:12px;color:#52606d;margin-bottom:6px}
.legend span{display:flex;align-items:center;gap:5px}.dot{width:10px;height:10px;border-radius:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
.card{border:1px solid #d9e2ec;border-radius:8px;overflow:hidden;background:#fff}
.frame{position:relative;aspect-ratio:1/1;overflow:hidden;background:#f0f4f8}.frame img{position:absolute;max-width:none;object-fit:fill}
.card.hidden{display:none}
.bar{display:flex;align-items:center;gap:6px;padding:5px 8px}.score{font-weight:700;font-size:16px}
.b{color:#fff;font-size:10px;padding:2px 6px;border-radius:9px}.conf{margin-left:auto;color:#9aa5b1;font-size:10px}
</style>
<h1>Smile validation &mdash; YuNet face + FER+ smile</h1>
<p>Sample of ${shown.length} faces from ${faces.length} detected so far (run in progress). Sorted by smile score. ${smiling} smiling, ${covered} mouth-covered.</p>
<div class="legend">
  <span><span class="dot" style="background:#1d9e75"></span>smiling</span>
  <span><span class="dot" style="background:#5f5e5a"></span>not smiling</span>
  <span><span class="dot" style="background:#a32d2d"></span>mouth covered (smile zeroed)</span>
</div>
<div class="bar-top"><label for="sl">Min smile score</label><input type="range" id="sl" min="0" max="1" step="0.01" value="0"><span class="thr" id="thr">0.00</span><span id="cnt"></span></div>
<div class="grid" id="grid">${shown.map(card).join("")}</div>
<script>
(function(){
  var sl=document.getElementById('sl'),thr=document.getElementById('thr'),cnt=document.getElementById('cnt');
  var cards=[].slice.call(document.querySelectorAll('.card'));
  function apply(){var t=parseFloat(sl.value);thr.textContent=t.toFixed(2);var n=0;
    cards.forEach(function(c){var s=parseFloat(c.getAttribute('data-smile'))||0;var hide=s<t;c.classList.toggle('hidden',hide);if(!hide)n++;});
    cnt.textContent=n+' / '+cards.length+' shown';}
  sl.addEventListener('input',apply);apply();
})();
</script>`;

  const outPath = path.join(fwmDataDir(repoRoot), "_reports", "smile_validation.html");
  await writeFile(outPath, html, "utf8");
  console.log(`Wrote ${outPath}`);
  console.log(`Faces ${faces.length} | shown ${shown.length} | smiling ${smiling} | covered ${covered}`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
