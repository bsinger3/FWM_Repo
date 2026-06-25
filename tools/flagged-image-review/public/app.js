// Flagged-image review UI. Loads the prebuilt dataset + saved decisions, renders a
// card per flagged image, and POSTs each Keep/Remove decision back to the server
// (which persists them to data/decisions.json). No DB access here.

let DATA = null;       // { dataset, decisions }
let reasonFilter = null;
let decisionFilter = "all";

const $ = (sel) => document.querySelector(sel);

async function load() {
  const res = await fetch("/api/dataset");
  DATA = await res.json();
  if (DATA.error) { $("#sub").textContent = "Error: " + DATA.error; return; }
  renderFilters();
  render();
}

function decisionOf(id) {
  return DATA.decisions[id]?.decision || "undecided";
}

function tallies() {
  let remove = 0, keep = 0;
  for (const e of DATA.dataset.entries) {
    const d = decisionOf(e.image_id);
    if (d === "remove") remove++;
    else if (d === "keep") keep++;
  }
  const undecided = DATA.dataset.entries.length - remove - keep;
  $("#tRemove").textContent = remove;
  $("#tKeep").textContent = keep;
  $("#tUndecided").textContent = undecided;
}

function renderFilters() {
  const { counts } = DATA.dataset;
  $("#sub").textContent =
    `${counts.flaggedImages} flagged images · ${counts.prodReports} prod + ${counts.devReports} dev reports` +
    (counts.missingFromDev ? ` · ${counts.missingFromDev} not in dev` : "");

  // Reason chips with counts.
  const byReason = {};
  for (const e of DATA.dataset.entries) for (const r of e.reasons) byReason[r] = (byReason[r] || 0) + 1;
  const labels = DATA.dataset.reasonLabels;
  const box = $("#reasonFilters");
  box.innerHTML = "";
  const allChip = chip("All reasons", DATA.dataset.entries.length, reasonFilter === null);
  allChip.onclick = () => { reasonFilter = null; render(); };
  box.appendChild(allChip);
  for (const [r, n] of Object.entries(byReason).sort((a, b) => b[1] - a[1])) {
    const c = chip(labels[r] || r, n, reasonFilter === r);
    if (r === "image_not_helpful") c.classList.add("help-chip");
    c.onclick = () => { reasonFilter = reasonFilter === r ? null : r; render(); };
    box.appendChild(c);
  }

  for (const b of document.querySelectorAll("#decisionSeg button")) {
    b.classList.toggle("active", b.dataset.dec === decisionFilter);
    b.onclick = () => { decisionFilter = b.dataset.dec; render(); };
  }
}

function chip(label, count, active) {
  const el = document.createElement("span");
  el.className = "chip" + (active ? " active" : "");
  el.innerHTML = `${label}<span class="c">${count}</span>`;
  return el;
}

function visibleEntries() {
  return DATA.dataset.entries.filter((e) => {
    if (reasonFilter && !e.reasons.includes(reasonFilter)) return false;
    if (decisionFilter !== "all" && decisionOf(e.image_id) !== decisionFilter) return false;
    return true;
  });
}

function render() {
  // keep chip active states in sync
  for (const c of document.querySelectorAll("#reasonFilters .chip")) {
    const lbl = c.firstChild.textContent;
    const labels = DATA.dataset.reasonLabels;
    const isAll = lbl === "All reasons";
    const matchKey = Object.keys(labels).find((k) => labels[k] === lbl) || lbl;
    c.classList.toggle("active", isAll ? reasonFilter === null : reasonFilter === matchKey);
  }
  for (const b of document.querySelectorAll("#decisionSeg button"))
    b.classList.toggle("active", b.dataset.dec === decisionFilter);

  tallies();
  const grid = $("#grid");
  grid.innerHTML = "";
  const entries = visibleEntries();
  if (!entries.length) {
    grid.innerHTML = `<div class="empty">No images match this filter.</div>`;
  } else {
    for (const e of entries) grid.appendChild(card(e));
  }
  $("#applyHint").innerHTML =
    `Showing ${entries.length} of ${DATA.dataset.entries.length}. ` +
    `Apply removals to dev with <code>npm run flagged-review:apply</code> (dry-run), then <code>-- --apply</code>.`;
}

function fmtUrl(u) {
  if (!u) return null;
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u.slice(0, 40); }
}

function card(e) {
  const img = e.image || {};
  const dec = decisionOf(e.image_id);
  const labels = DATA.dataset.reasonLabels;
  const el = document.createElement("div");
  el.className = "card" + (dec !== "undecided" ? ` dec-${dec}` : "") + (e.already_removed ? " removed-flag" : "");

  // thumbnail + badges
  const thumb = document.createElement("div");
  thumb.className = "thumb";
  const url = img.original_url_display;
  if (url) {
    thumb.innerHTML =
      `<img loading="lazy" src="${escapeAttr(url)}" alt="" referrerpolicy="no-referrer" ` +
      `onerror="this.style.display='none';this.parentElement.insertAdjacentHTML('beforeend','<div class=noimg>image failed to load<br>(${escapeAttr(fmtUrl(url) || "")})</div>')" />` +
      `<a href="${escapeAttr(url)}" target="_blank" rel="noreferrer" title="Open image"></a>`;
  } else {
    thumb.innerHTML = `<div class="noimg">no image url${e.in_dev_images ? "" : "<br>(not in dev)"}</div>`;
  }
  const badges = document.createElement("div");
  badges.className = "badges";
  if (e.reasons.includes("image_not_helpful")) badges.innerHTML += `<span class="badge help">not helpful</span>`;
  for (const o of e.origins) badges.innerHTML += `<span class="badge origin">${o}</span>`;
  if (e.report_count > 1) badges.innerHTML += `<span class="badge origin">×${e.report_count}</span>`;
  if (e.already_removed) badges.innerHTML += `<span class="badge removed">removed</span>`;
  thumb.appendChild(badges);
  el.appendChild(thumb);

  // body
  const body = document.createElement("div");
  body.className = "body";

  const reasons = document.createElement("div");
  reasons.className = "reasons";
  for (const r of e.reasons) {
    const t = document.createElement("span");
    t.className = "rtag" + (r === "image_not_helpful" ? " help" : "");
    t.textContent = labels[r] || r;
    reasons.appendChild(t);
  }
  body.appendChild(reasons);

  const meta = document.createElement("div");
  meta.className = "meta";
  let metaHtml = "";
  if (img.user_comment) metaHtml += `<div class="comment">“${escapeHtml(img.user_comment)}”</div>`;
  const kv = [];
  if (img.brand) kv.push(img.brand);
  if (img.clothing_type_id) kv.push(img.clothing_type_id);
  if (img.size_display) kv.push("size " + img.size_display);
  if (img.color_display) kv.push(img.color_display);
  if (img.prettiness_score != null) kv.push("pretty " + img.prettiness_score);
  if (kv.length) metaHtml += `<div class="kv">${kv.map((x) => `<span>${escapeHtml(String(x))}</span>`).join("")}</div>`;
  const links = [];
  if (img.source_site_display) links.push(`<a href="${escapeAttr(img.source_site_display)}" target="_blank" rel="noreferrer">${fmtUrl(img.source_site_display)}</a>`);
  if (img.product_page_url_display) links.push(`<a href="${escapeAttr(img.product_page_url_display)}" target="_blank" rel="noreferrer">product</a>`);
  if (links.length) metaHtml += `<div>${links.join(" · ")}</div>`;
  meta.innerHTML = metaHtml || `<span style="color:#5b6470">(no preview fields in dev)</span>`;
  body.appendChild(meta);

  const idline = document.createElement("div");
  idline.className = "idline";
  idline.textContent = e.image_id;
  body.appendChild(idline);

  // actions
  const actions = document.createElement("div");
  actions.className = "actions";
  const removeBtn = document.createElement("button");
  removeBtn.className = "remove" + (dec === "remove" ? " on" : "");
  removeBtn.textContent = dec === "remove" ? "✓ Remove" : "Remove";
  removeBtn.onclick = () => decide(e.image_id, dec === "remove" ? "undecided" : "remove");
  const keepBtn = document.createElement("button");
  keepBtn.className = "keep" + (dec === "keep" ? " on" : "");
  keepBtn.textContent = dec === "keep" ? "✓ Keep" : "Keep";
  keepBtn.onclick = () => decide(e.image_id, dec === "keep" ? "undecided" : "keep");
  actions.appendChild(keepBtn);
  actions.appendChild(removeBtn);
  body.appendChild(actions);

  el.appendChild(body);
  return el;
}

async function decide(image_id, decision) {
  const res = await fetch("/api/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_id, decision }),
  });
  const out = await res.json();
  if (out.error) { alert(out.error); return; }
  DATA.decisions = out.decisions;
  render();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
function escapeAttr(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

load();
