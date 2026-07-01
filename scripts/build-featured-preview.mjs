#!/usr/bin/env node

// Preview the CLIP-featured "best photos": joins clip_aesthetic.ndjson (scores) to
// clip_shortlist.ndjson (url + autocrop rect), renders the top N auto-cropped cards
// sorted by aesthetic score. Read-only; writes _reports/featured_preview.html.

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const dataDir = fwmDataDir(repoRoot);
const TOP = Math.max(1, Number(process.argv.find((a) => a.startsWith("--top="))?.slice(6) || "100"));

const esc = (s) => String(s ?? "").replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
const readNd = async (p) => (await readFile(p, "utf8")).split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));

async function main() {
  const aes = new Map((await readNd(path.join(dataDir, "_cache", "clip_aesthetic.ndjson"))).map((r) => [r.id, r.aesthetic]));
  const short = await readNd(path.join(dataDir, "_cache", "clip_shortlist.ndjson"));
  const rows = short
    .filter((r) => Number.isFinite(aes.get(r.id)))
    .map((r) => ({ ...r, aesthetic: aes.get(r.id) }))
    .sort((a, b) => b.aesthetic - a.aesthetic)
    .slice(0, TOP);

  const card = (r, i) => {
    const c = r.crop;
    const img = c
      ? `<img loading="lazy" src="${esc(r.url)}" style="width:${(100 / c.widthFrac).toFixed(1)}%;height:${(100 / c.heightFrac).toFixed(1)}%;left:${(-(c.leftFrac / c.widthFrac) * 100).toFixed(1)}%;top:${(-(c.topFrac / c.heightFrac) * 100).toFixed(1)}%;position:absolute;max-width:none;object-fit:fill">`
      : `<img loading="lazy" src="${esc(r.url)}" style="width:100%;height:100%;object-fit:cover">`;
    return `<div class="card"><div class="frame">${img}</div><div class="bar"><span class="rank">#${i + 1}</span><span class="score">${r.aesthetic.toFixed(2)}</span></div></div>`;
  };

  const html = `<!doctype html><meta charset="utf-8"><title>CLIP featured — top ${rows.length}</title>
<style>body{font-family:system-ui,sans-serif;margin:22px;color:#1f2933}h1{font-size:20px}p{color:#52606d;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #d9e2ec;border-radius:8px;overflow:hidden;background:#fff}
.frame{position:relative;aspect-ratio:3/4;overflow:hidden;background:#f0f4f8}
.bar{display:flex;justify-content:space-between;padding:6px 9px;font-size:13px}
.rank{color:#9aa5b1}.score{font-weight:700;color:#1d9e75}</style>
<h1>CLIP-featured "best photos" — top ${rows.length}</h1>
<p>Auto-cropped cards, ranked by LAION aesthetic score (CLIP ViT-L/14). These are what now populate the random page load.</p>
<div class="grid">${rows.map(card).join("")}</div>`;
  const outPath = path.join(dataDir, "_reports", "featured_preview.html");
  await writeFile(outPath, html, "utf8");
  console.log(`Wrote ${outPath} (${rows.length} cards)`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
