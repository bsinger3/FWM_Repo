#!/usr/bin/env node
/**
 * Build a self-contained, browsable HTML review sheet of the harvested Reddit
 * posts. Reads the cleaned NDJSON and embeds the FULL record for every post so
 * nothing is hidden — the table is a compact index, and each row expands to a
 * detail panel showing all captured fields (full text, every measurement + the
 * exact raw substrings matched, every image URL with verify status + thumbnail,
 * author, flair, exact timestamps, id, tier, source, permalink).
 *
 * Output lands in the gitignored .codex_tmp/ inside the repo so the in-app file
 * viewer can open it (FWM_Data lives outside the repo and the viewer can't read
 * across that boundary). Writes nothing to Supabase.
 *
 * Usage: node scripts/build-reddit-review.mjs
 */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(__dirname, "..");
const IN = resolve(REPO, "../FWM_Data/reddit_harvest/posts_clean.ndjson");
const OUT_DIR = resolve(REPO, ".codex_tmp");
const OUT = resolve(OUT_DIR, "reddit_review.html");

const rows = (await readFile(IN, "utf8")).split("\n").filter(Boolean).map((l) => JSON.parse(l));
// Newest first within: measured posts before unmeasured.
rows.sort((a, b) => (Number(b.has_measurements) - Number(a.has_measurements)) || (Date.parse(b.created_utc) - Date.parse(a.created_utc)));

const now = Date.now();
const ageStr = (iso) => {
  const d = (now - Date.parse(iso)) / 86400000;
  if (isNaN(d)) return "?";
  if (d < 1) return `${Math.round(d * 24)}h`;
  return `${Math.round(d)}d`;
};
const measSummary = (m) =>
  m ? Object.entries(m).filter(([k]) => k !== "raw").map(([k, v]) => `${k.replace(/_in$|_lbs$/, "")}=${v}`).join(", ") : "";

const nMeas = (m) => (m ? Object.keys(m).filter((k) => k !== "raw").length : 0);
const DATA = JSON.stringify(rows.map((r) => ({ ...r, _age: ageStr(r.created_utc), _meas: measSummary(r.measurements), _nmeas: nMeas(r.measurements) })));

const html = `<!doctype html><meta charset=utf-8><title>Reddit harvest review</title>
<style>
:root{--bd:#e5e5e5;--mut:#777;--accent:#06c}
*{box-sizing:border-box}
body{font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:16px;color:#1a1a1a}
h1{font-size:18px;margin:0 0 2px}.subtitle{color:var(--mut);font-size:13px;margin-bottom:10px}
#bar{position:sticky;top:0;background:#fff;padding:10px 0;border-bottom:1px solid var(--bd);display:flex;gap:8px;flex-wrap:wrap;align-items:center;z-index:9}
input,select{font:13px sans-serif;padding:6px 8px;border:1px solid #ccc;border-radius:6px}#q{flex:1;min-width:220px}
table{border-collapse:collapse;width:100%;margin-top:8px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}
th{position:sticky;top:53px;background:#fafafa;cursor:pointer;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#666;white-space:nowrap}
tr.row{cursor:pointer}tr.row:hover{background:#f7f9ff}
.tog{color:var(--mut);width:14px;display:inline-block}
.meas{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#eef6ff;color:#076;padding:1px 5px;border-radius:4px;white-space:nowrap}.meas:empty{display:none}
.cloth{color:#96642a;font-size:12px}.sm{color:var(--mut);font-size:12px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.detail{background:#fbfbfd}.detail td{padding:0}
.card{padding:12px 16px;display:grid;grid-template-columns:140px 1fr;gap:6px 16px;border-left:3px solid var(--accent);margin:2px 0}
.card dt{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
.card dd{margin:0;word-break:break-word}
.rawtext{white-space:pre-wrap;background:#fff;border:1px solid var(--bd);border-radius:6px;padding:8px;max-height:260px;overflow:auto;font-size:13px}
.kv{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.badge{display:inline-block;font-size:11px;padding:1px 6px;border-radius:10px;margin-left:6px}
.ok{background:#e6f6ea;color:#137a2b}.bad{background:#fdeaea;color:#b3261e}
.thumbs{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.thumbs figure{margin:0;width:120px}.thumbs img{width:120px;height:120px;object-fit:cover;border-radius:6px;border:1px solid var(--bd);background:#f3f3f3}
.thumbs figcaption{font-size:10px;color:var(--mut);word-break:break-all}
.rawmatch{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#555}
</style>
<h1>Reddit harvest — full review</h1>
<div class=subtitle>Every captured field per post. Cleaned, bounds-checked; NSFW subs removed. Nothing loaded to dev. Click a row to expand.</div>
<div id=bar>
  <input id=q placeholder="search title / text / measurements / author…">
  <select id=fsub></select>
  <select id=sort title="sort order">
    <option value="new">⏱ Newest first</option>
    <option value="old">⏱ Oldest first</option>
    <option value="sub">Subreddit A–Z</option>
    <option value="meas">Most measurements</option>
    <option value="img">Most images</option>
  </select>
  <label class=sm><input type=checkbox id=fmeas> measured only</label>
  <label class=sm><input type=checkbox id=fimg> has image only</label>
  <span class=sm><span id=n style=font-weight:600></span> of ${rows.length} shown</span>
  <button id=expand class=sm style="cursor:pointer">expand all</button>
</div>
<table><thead><tr>
<th style=width:14px></th><th data-k=subreddit>sub</th><th data-k=created_utc>age</th>
<th data-k=title>title</th><th data-k=flair>flair</th><th data-k=_meas>measurements</th>
<th data-k=clothing>clothing</th><th data-k=image_ok_count>img</th><th data-k=author>author</th>
</tr></thead><tbody id=tb></tbody></table>
<script>
const D=${DATA};
let sortK="created_utc",asc=false,allOpen=false;
const subs=[...new Set(D.map(d=>d.subreddit))].sort();
fsub.innerHTML="<option value=''>all subs</option>"+subs.map(s=>"<option>"+s+"</option>").join("");
const esc=s=>(s==null?"":(""+s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]));
function detail(d){
  const m=d.measurements||{};
  const measRows=Object.entries(m).filter(([k])=>k!=="raw").map(([k,v])=>\`<span class=kv>\${k} = <b>\${esc(v)}</b></span>\`).join("&nbsp;&nbsp;")||"<span class=sm>none parsed</span>";
  const raw=(m.raw||[]).map(x=>esc(x)).join(" · ");
  const imgs=(d.image_urls||[]).map(im=>{
    const ok=im.status>=200&&im.status<300;
    return \`<figure><a href="\${esc(im.url)}" target=_blank><img loading=lazy src="\${esc(im.url)}"></a><figcaption>\${ok?'<span class="badge ok">'+im.status+'</span>':'<span class="badge bad">'+(im.status||'?')+'</span>'} \${esc(im.url)}</figcaption></figure>\`;
  }).join("")||"<span class=sm>no images</span>";
  return \`<div class=card>
   <dt>permalink</dt><dd><a href="\${esc(d.permalink)}" target=_blank>\${esc(d.permalink)}</a></dd>
   <dt>title</dt><dd>\${esc(d.title)}</dd>
   <dt>subreddit</dt><dd>r/\${esc(d.subreddit)} <span class=sm>(tier: \${esc(d.tier)})</span></dd>
   <dt>author</dt><dd>\${esc(d.author)}</dd>
   <dt>posted</dt><dd>\${esc(d.created_utc)} <span class=sm>(\${esc(d._age)} ago)</span></dd>
   <dt>flair</dt><dd>\${esc(d.flair)||"<span class=sm>—</span>"}</dd>
   <dt>clothing guess</dt><dd class=cloth>\${esc((d.clothing_request||[]).join(", "))}</dd>
   <dt>measurements</dt><dd>\${measRows}\${raw?'<br><span class=rawmatch>matched: '+raw+'</span>':''}</dd>
   <dt>images (\${d.image_ok_count||0} ok / \${(d.image_urls||[]).length})</dt><dd><div class=thumbs>\${imgs}</div></dd>
   <dt>full text</dt><dd><div class=rawtext>\${esc(d.raw_text)||"<span class=sm>(empty — image/gallery post)</span>"}</div></dd>
   <dt>meta</dt><dd class=sm>id \${esc(d.id)} · source \${esc(d.source)} · harvested \${esc(d.harvested_at)}</dd>
  </div>\`;
}
function render(){
  let r=D.filter(d=>{
    if(fmeas.checked&&!d.has_measurements)return false;
    if(fimg.checked&&!(d.image_urls||[]).length)return false;
    if(fsub.value&&d.subreddit!=fsub.value)return false;
    const q=qel.value.toLowerCase();
    if(q&&!((d.title+d.raw_text+d._meas+d.author).toLowerCase().includes(q)))return false;
    return true;});
  r.sort((a,b)=>{let x=a[sortK],y=b[sortK];
    if(sortK=="image_ok_count"||sortK=="_nmeas")return asc?(x||0)-(y||0):(y||0)-(x||0);
    if(sortK=="created_utc")return asc?Date.parse(x)-Date.parse(y):Date.parse(y)-Date.parse(x);
    return asc?(""+x).localeCompare(""+y):(""+y).localeCompare(""+x);});
  n.textContent=r.length;
  tb.innerHTML=r.map((d,i)=>\`<tr class=row data-i=\${i}><td class=tog>\${allOpen?"▾":"▸"}</td><td>r/\${esc(d.subreddit)}</td><td class=sm>\${esc(d._age)}</td>
   <td><a href="\${esc(d.permalink)}" target=_blank onclick="event.stopPropagation()">\${esc(d.title)}</a></td>
   <td class=cloth>\${esc(d.flair)}</td>
   <td><span class=meas>\${esc(d._meas)}</span></td><td class=cloth>\${esc((d.clothing_request||[]).join(", "))}</td>
   <td>\${d.image_ok_count||""}</td><td class=sm>\${esc(d.author)}</td></tr>
   <tr class=detail data-d=\${i} style="display:\${allOpen?"table-row":"none"}"><td colspan=9>\${detail(d)}</td></tr>\`).join("");
  cur=r;
}
let cur=[];
tb.addEventListener("click",e=>{const tr=e.target.closest("tr.row");if(!tr)return;
  const dr=tr.nextElementSibling;const open=dr.style.display!=="none";
  dr.style.display=open?"none":"table-row";tr.firstChild.textContent=open?"▸":"▾";});
const qel=document.getElementById("q");
const SORTS={new:["created_utc",false],old:["created_utc",true],sub:["subreddit",true],meas:["_nmeas",false],img:["image_ok_count",false]};
const sortSel=document.getElementById("sort");
sortSel.onchange=()=>{[sortK,asc]=SORTS[sortSel.value];render();};
qel.oninput=fsub.onchange=fmeas.onchange=fimg.onchange=render;
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k;asc=sortK==k?!asc:true;sortK=k;sortSel.value="";render();});
document.getElementById("expand").onclick=function(){allOpen=!allOpen;this.textContent=allOpen?"collapse all":"expand all";render();};
render();
</script>`;

await mkdir(OUT_DIR, { recursive: true });
await writeFile(OUT, html, "utf8");
console.log(`Wrote ${OUT} — ${rows.length} posts, ${(html.length / 1024 / 1024).toFixed(1)}MB`);
