#!/usr/bin/env node

// Builds an interactive prettiness REVIEW dashboard from a scorer report JSON
// (score-dev-image-prettiness.mjs output). On top of the score gallery it lets you:
//   - write a free-text comment per image (for ones whose score looks wrong),
//   - tag images with labels from a palette (seeded: bad lighting / cluttered
//     background / hazy picture) and ADD your own labels,
//   - multi-select images and BULK-apply (or remove) a label,
//   - filter by min prettiness (slider) or "only annotated",
//   - Save straight into _reports (via the label server's /save-annotations) so
//     Claude can read your comments and turn the recurring ones into labels.
//
//   node scripts/build-prettiness-review-dashboard.mjs            # newest report
//   node scripts/build-prettiness-review-dashboard.mjs --input <report.json>

import { readFile, writeFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");

function parseArg(name, def = null) {
  const m = process.argv.find((a) => a.startsWith(`--${name}=`));
  if (m) return m.slice(name.length + 3);
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : def;
}

async function newestReport() {
  const files = (await readdir(reportsDir))
    .filter((f) => /^dev_image_prettiness_score_dryrun_.*\.json$/.test(f))
    .sort();
  if (!files.length) throw new Error("no prettiness report JSON found in _reports");
  return path.join(reportsDir, files[files.length - 1]);
}

function htmlEscape(v) {
  return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

async function main() {
  const inputPath = parseArg("input") || (await newestReport());
  const report = JSON.parse(await readFile(inputPath, "utf8"));
  const rows = report.results
    .filter((r) => !r.skipped && r.prettiness_score != null)
    .sort((a, b) => b.prettiness_score - a.prettiness_score)
    .map((r) => {
      const c = r.components || {};
      return {
        id: r.image_id,
        url: r.image_url,
        score: r.prettiness_score,
        win: r.crop_window && r.crop_window.widthFrac ? r.crop_window : null,
        m: {
          light: c.lighting_score,
          color: c.colorfulness_score,
          clutter: c.background_clutter_score,
          face: c.face_visible_score,
          smile: c.smile_score,
          body: c.body_visible_score,
          comp: c.composition_score,
        },
      };
    });

  const data = JSON.stringify(rows);
  const stem = path.basename(inputPath).replace(/\.json$/, "");
  const html = `<!doctype html><meta charset="utf-8"><title>Prettiness review</title>
<style>
  body{font-family:system-ui,sans-serif;margin:20px;color:#1f2933}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:#52606d;font-size:13px;margin:0 0 12px}
  .toolbar{position:sticky;top:0;background:#fff;border-bottom:1px solid #d9e2ec;padding:10px 0;margin-bottom:14px;z-index:20}
  .toolbar .row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:5px 0}
  .toolbar input[type=range]{flex:1;min-width:200px;max-width:420px}
  .thr{font-weight:700;min-width:3em;font-variant-numeric:tabular-nums}
  button{font:inherit;border:1px solid #b9c2cf;background:#fff;border-radius:6px;padding:5px 10px;cursor:pointer}
  button:hover{background:#f0f4f8}
  button.primary{border-color:#1d9e75;color:#0f6e56;font-weight:600}
  input[type=text]{font:inherit;border:1px solid #b9c2cf;border-radius:6px;padding:5px 8px}
  select{font:inherit;border:1px solid #b9c2cf;border-radius:6px;padding:5px 8px}
  .palette{display:flex;gap:6px;flex-wrap:wrap}
  .pchip{font-size:12px;background:#eef2f7;border:1px solid #d9e2ec;border-radius:12px;padding:3px 9px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
  .card{border:1px solid #d9e2ec;border-radius:8px;overflow:hidden;background:#fff;position:relative}
  .card.hidden{display:none}
  .card.sel{outline:3px solid #1d9e75;outline-offset:-3px}
  .frame{position:relative;aspect-ratio:3/4;overflow:hidden;background:#f0f4f8;cursor:pointer}
  .frame img{width:100%;height:100%;object-fit:cover}
  .frame img.win{position:absolute;max-width:none;object-fit:fill}
  .pick{position:absolute;top:6px;left:6px;width:20px;height:20px;z-index:2;cursor:pointer}
  .score{font-weight:700;font-size:17px;padding:5px 8px 0}
  .meta{font-size:11px;color:#52606d;padding:1px 8px}
  .labels{display:flex;gap:4px;flex-wrap:wrap;padding:4px 8px 0}
  .lchip{font-size:11px;background:#fce8d8;border:1px solid #f0c39a;color:#8a4b16;border-radius:10px;padding:2px 7px;cursor:pointer}
  .lchip:hover{background:#f7d9bf}
  .comment{width:calc(100% - 16px);margin:6px 8px 8px;box-sizing:border-box}
  .commented{box-shadow:inset 3px 0 0 #1d9e75}
  #count,#selcount{color:#52606d;font-size:13px}
</style>
<h1>Prettiness review &mdash; comment &amp; label</h1>
<p class="sub">${rows.length} images from <code>${htmlEscape(stem)}</code>, sorted by prettiness. Comment on any that look wrong; tag with labels (select cards &amp; bulk-apply). Saves into <code>_reports/</code> for Claude to read.</p>
<div class="toolbar">
  <div class="row">
    <label for="sl">Min prettiness</label><input type="range" id="sl" min="0" max="1" step="0.01" value="0"><span class="thr" id="thr">0.00</span>
    <label><input type="checkbox" id="onlyann"> only annotated</label>
    <span id="count"></span>
  </div>
  <div class="row">
    <strong>Labels:</strong><span class="palette" id="palette"></span>
    <input type="text" id="newlabel" placeholder="add a label…" size="16"><button id="addlabel">+ add</button>
  </div>
  <div class="row">
    <strong>Bulk:</strong><select id="bulklabel"></select>
    <button id="applybtn">Apply to selected</button><button id="removebtn">Remove from selected</button>
    <button id="clearsel">Clear selection</button><span id="selcount">0 selected</span>
  </div>
  <div class="row">
    <button id="save" class="primary">Save to _reports</button>
    <button id="download">Download JSON</button><button id="copy">Copy JSON</button>
    <button id="clearann">Clear all annotations</button>
  </div>
</div>
<div class="grid" id="grid"></div>
<script>
(function(){
  var ROWS = ${data};
  var SOURCE = ${JSON.stringify(stem)};
  var AKEY = "prettiness_annotations_v1", PKEY = "prettiness_label_palette_v1";
  var ann = JSON.parse(localStorage.getItem(AKEY) || "{}");
  var palette = JSON.parse(localStorage.getItem(PKEY) || "null") || ["bad lighting","cluttered background","hazy picture"];
  var selected = {};
  function saveLocal(){ localStorage.setItem(AKEY, JSON.stringify(ann)); }
  function savePalette(){ localStorage.setItem(PKEY, JSON.stringify(palette)); }
  function getA(id){ return ann[id] || (ann[id] = {comment:"", labels:[]}); }
  function isAnnotated(id){ var a=ann[id]; return a && (a.comment || (a.labels && a.labels.length)); }

  function frameImg(r){
    if(r.win){var w=r.win; return '<img class="win" loading="lazy" src="'+esc(r.url)+'" style="width:'+(100/w.widthFrac).toFixed(2)+'%;height:'+(100/w.heightFrac).toFixed(2)+'%;left:'+(-(w.leftFrac/w.widthFrac)*100).toFixed(2)+'%;top:'+(-(w.topFrac/w.heightFrac)*100).toFixed(2)+'%">';}
    return '<img loading="lazy" src="'+esc(r.url)+'">';
  }
  function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;");}
  function fmt(v){return v==null?"–":(+v).toFixed(2);}

  var grid=document.getElementById("grid");
  grid.innerHTML = ROWS.map(function(r){
    var m=r.m;
    return '<article class="card" data-id="'+esc(r.id)+'" data-score="'+r.score+'">'+
      '<div class="frame"><input type="checkbox" class="pick" title="select">'+frameImg(r)+'</div>'+
      '<div class="score">'+r.score.toFixed(3)+'</div>'+
      '<div class="meta">light '+fmt(m.light)+' · color '+fmt(m.color)+' · clutter '+fmt(m.clutter)+'</div>'+
      '<div class="meta">face '+fmt(m.face)+' · smile '+fmt(m.smile)+' · body '+fmt(m.body)+' · comp '+fmt(m.comp)+'</div>'+
      '<div class="labels"></div>'+
      '<input type="text" class="comment" placeholder="comment if this score looks wrong…">'+
      '</article>';
  }).join("");
  var cards={};
  [].forEach.call(grid.querySelectorAll(".card"), function(c){ cards[c.getAttribute("data-id")]=c; });

  function renderCard(id){
    var c=cards[id]; if(!c) return; var a=ann[id]||{comment:"",labels:[]};
    var lab=c.querySelector(".labels");
    lab.innerHTML=(a.labels||[]).map(function(l){return '<span class="lchip" data-l="'+esc(l)+'">'+esc(l)+' ×</span>';}).join("");
    [].forEach.call(lab.querySelectorAll(".lchip"), function(ch){ ch.onclick=function(){ removeLabel(id, ch.getAttribute("data-l")); }; });
    var ci=c.querySelector(".comment"); if(ci.value!==(a.comment||"")) ci.value=a.comment||"";
    c.classList.toggle("commented", !!(a.comment||(a.labels&&a.labels.length)));
  }
  function addLabel(id,l){ var a=getA(id); if(a.labels.indexOf(l)<0){a.labels.push(l);saveLocal();renderCard(id);} }
  function removeLabel(id,l){ var a=getA(id); a.labels=a.labels.filter(function(x){return x!==l;}); saveLocal(); renderCard(id); }

  // comments
  grid.addEventListener("input", function(e){ if(e.target.classList.contains("comment")){ var id=e.target.closest(".card").getAttribute("data-id"); getA(id).comment=e.target.value; saveLocal(); cards[id].classList.toggle("commented",!!(ann[id].comment||ann[id].labels.length)); } });
  // selection
  grid.addEventListener("change", function(e){ if(e.target.classList.contains("pick")){ var c=e.target.closest(".card"); var id=c.getAttribute("data-id"); if(e.target.checked){selected[id]=1;c.classList.add("sel");}else{delete selected[id];c.classList.remove("sel");} updateSel(); } });
  function updateSel(){ document.getElementById("selcount").textContent=Object.keys(selected).length+" selected"; }
  function selectedVisibleIds(){ return Object.keys(selected); }

  // palette + bulk select
  function renderPalette(){
    document.getElementById("palette").innerHTML=palette.map(function(l){return '<span class="pchip">'+esc(l)+'</span>';}).join("");
    var sel=document.getElementById("bulklabel"); sel.innerHTML=palette.map(function(l){return '<option>'+esc(l)+'</option>';}).join("");
  }
  document.getElementById("addlabel").onclick=function(){ var v=document.getElementById("newlabel").value.trim(); if(v&&palette.indexOf(v)<0){palette.push(v);savePalette();renderPalette();} document.getElementById("newlabel").value=""; };
  document.getElementById("applybtn").onclick=function(){ var l=document.getElementById("bulklabel").value; selectedVisibleIds().forEach(function(id){addLabel(id,l);}); };
  document.getElementById("removebtn").onclick=function(){ var l=document.getElementById("bulklabel").value; selectedVisibleIds().forEach(function(id){removeLabel(id,l);}); };
  document.getElementById("clearsel").onclick=function(){ Object.keys(selected).forEach(function(id){var c=cards[id];if(c){c.classList.remove("sel");var p=c.querySelector(".pick");if(p)p.checked=false;}}); selected={}; updateSel(); };

  // filters
  var sl=document.getElementById("sl"), thr=document.getElementById("thr"), onlyann=document.getElementById("onlyann");
  function applyFilter(){ var t=parseFloat(sl.value); thr.textContent=t.toFixed(2); var oa=onlyann.checked; var n=0;
    ROWS.forEach(function(r){ var c=cards[r.id]; var hide=r.score<t || (oa && !isAnnotated(r.id)); c.classList.toggle("hidden",hide); if(!hide)n++; });
    document.getElementById("count").textContent=n+" / "+ROWS.length+" shown";
  }
  sl.addEventListener("input",applyFilter); onlyann.addEventListener("change",applyFilter);

  // export / save
  function buildExport(){ var out=[]; Object.keys(ann).forEach(function(id){ var a=ann[id]; if(a.comment||(a.labels&&a.labels.length)){ var r=ROWS.filter(function(x){return x.id===id;})[0]; out.push({image_id:id, prettiness_score:r?r.score:null, comment:a.comment||"", labels:a.labels||[]}); } });
    return JSON.stringify({save_name:"prettiness_annotations", source_report:SOURCE, exported_at:new Date().toISOString(), palette:palette, annotations:out},null,2); }
  document.getElementById("save").onclick=function(){ var btn=this; var body=buildExport(); var n=JSON.parse(body).annotations.length; if(!n){alert("No comments or labels yet.");return;} btn.disabled=true;btn.textContent="Saving…";
    fetch("/save-annotations",{method:"POST",headers:{"Content-Type":"application/json"},body:body}).then(function(r){return r.json();}).then(function(j){btn.disabled=false;btn.textContent="Save to _reports"; if(j.ok)alert("Saved "+n+" annotations to:\\n"+j.path+"\\n\\nTell Claude it's saved."); else alert("Save failed: "+j.error);}).catch(function(e){btn.disabled=false;btn.textContent="Save to _reports";alert("Save server not reachable ("+e.message+"). Use Download/Copy.");}); };
  document.getElementById("download").onclick=function(){ var b=new Blob([buildExport()],{type:"application/json"}); var a=document.createElement("a"); a.href=URL.createObjectURL(b); a.download="prettiness_annotations_"+new Date().toISOString().replace(/[:.]/g,"-")+".json"; a.click(); };
  document.getElementById("copy").onclick=function(){ navigator.clipboard.writeText(buildExport()).then(function(){var n=JSON.parse(buildExport()).annotations.length;alert("Copied "+n+" annotations.");}); };
  document.getElementById("clearann").onclick=function(){ if(confirm("Clear ALL comments and labels?")){ann={};saveLocal();ROWS.forEach(function(r){renderCard(r.id);});} };

  // init
  renderPalette(); ROWS.forEach(function(r){ renderCard(r.id); }); applyFilter(); updateSel();
})();
</script>`;

  const outPath = path.join(reportsDir, "prettiness_review.html");
  await writeFile(outPath, html, "utf8");
  console.log(`Wrote ${outPath}`);
  console.log(`Images ${rows.length} | source ${stem}`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exitCode = 1;
});
