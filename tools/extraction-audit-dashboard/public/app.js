const state = {
  queue: [],        // ordered ids for the current filter (fixed per load)
  cursor: 0,        // start index of the current page within queue
  pageSize: 25,
  markedThisSession: new Set(), // ids hidden after marking, without reflowing the queue
  status: "unreviewed",
  site: "",
  minSuspicion: "0",
  commented: "",
  q: "",
};

const el = (id) => document.getElementById(id);
const listEl = el("list");

const MEASURE_LABELS = [
  ["heightIn", "Height (in)"],
  ["weightLbs", "Weight (lb)"],
  ["bustIn", "Bust (in)"],
  ["braBandIn", "Bra band (in)"],
  ["cupSize", "Cup size"],
  ["waistIn", "Waist (in)"],
  ["hipsIn", "Hips (in)"],
  ["inseamIn", "Inseam (in)"],
  ["ageYears", "Age (yrs)"],
  ["weeksPregnant", "Pregnancy (wks)"],
  ["size", "Size"],
];

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function renderComment(segments) {
  if (!segments?.length) return '<span class="empty">(no comment)</span>';
  return segments
    .map((s) => (s.type === "plain" ? esc(s.text) : `<mark class="${s.type}">${esc(s.text)}</mark>`))
    .join("");
}

function renderMeasures(extracted) {
  const rows = MEASURE_LABELS.map(([key, label]) => {
    const val = String(extracted[key] ?? "").trim();
    if (!val) return `<tr><td class="k">${label}</td><td class="v empty">—</td></tr>`;
    const display =
      val.length > 24
        ? `<span class="long" title="${esc(val)}">⚠ ${esc(val.slice(0, 24))}…</span>`
        : esc(val);
    return `<tr><td class="k">${label}</td><td class="v">${display}</td></tr>`;
  }).join("");
  return `<div class="measures"><table><thead><tr><th colspan="2">Extracted measurements (live regex)</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function card(r) {
  const f = r.flag || {};
  const div = document.createElement("article");
  div.className = "card" + (f.state ? ` reviewed-${f.state}` : "");
  div.dataset.id = r.id;

  const thumb = r.imageUrl
    ? `<img class="thumb" loading="lazy" src="${esc(r.imageUrl)}" data-fallback="${esc(r.rawImageUrl || "")}" alt="review image" />`
    : `<div class="thumb thumb-missing">no image url</div>`;

  const meta = [
    `<span class="tag dec-${esc(r.decision || "")}">${esc(r.decision || "—")}</span>`,
    `<span class="tag susp">suspicion ${r.suspicion}</span>`,
    r.duplicateCount > 1 ? `<span class="tag dup">in ${r.duplicateCount} images</span>` : "",
    r.sourceSite ? `<span class="tag">${esc(r.sourceSite)}</span>` : "",
    r.brand ? `<span class="tag">${esc(r.brand)}</span>` : "",
    r.clothingType ? `<span class="tag">${esc(r.clothingType)}</span>` : "",
  ].join("");

  const reviewNote = r.reviewNote
    ? `<div class="review-note"><b>Your dashboard comment:</b> ${esc(r.reviewNote)}</div>`
    : "";

  div.innerHTML = `
    <div class="thumb-wrap">
      ${thumb}
      ${r.productUrl ? `<a href="${esc(r.productUrl)}" target="_blank" rel="noopener">product ↗</a>` : ""}
    </div>
    <div class="mid">
      <div class="meta">${meta}</div>
      <div class="comment">${renderComment(r.segments)}</div>
      ${reviewNote}
    </div>
    <div class="right">
      ${renderMeasures(r.extracted)}
      <div class="review">
        <div class="review-buttons">
          <button class="btn-correct ${f.state === "correct" ? "on" : ""}">✓ Correct</button>
          <button class="btn-incorrect ${f.state === "incorrect" ? "on" : ""}">⚑ Incorrect</button>
        </div>
        <textarea class="note" placeholder="What's wrong / the correct measurements (seeds the regex test)…">${esc(f.note || "")}</textarea>
      </div>
    </div>`;

  const img = div.querySelector(".thumb");
  if (img) {
    img.addEventListener("error", () => {
      const fb = img.getAttribute("data-fallback");
      if (fb && img.src !== fb) {
        img.src = fb;
        img.removeAttribute("data-fallback");
      } else {
        const ph = document.createElement("div");
        ph.className = "thumb thumb-missing";
        ph.textContent = "image failed to load";
        img.replaceWith(ph);
      }
    });
  }

  const noteEl = div.querySelector(".note");
  const correctBtn = div.querySelector(".btn-correct");
  const incorrectBtn = div.querySelector(".btn-incorrect");

  const mark = async (st) => {
    await fetch("/api/flag", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: r.id, state: st, note: noteEl.value }),
    });
    // In unreviewed mode the row is done — hide it and don't show it again.
    if (state.status === "unreviewed") {
      state.markedThisSession.add(r.id);
      div.classList.add("removing");
      setTimeout(() => {
        div.remove();
        refreshCounts(st);
        if (!listEl.querySelector(".card")) renderPage();
      }, 220);
    } else {
      div.classList.remove("reviewed-correct", "reviewed-incorrect");
      div.classList.add(`reviewed-${st}`);
      correctBtn.classList.toggle("on", st === "correct");
      incorrectBtn.classList.toggle("on", st === "incorrect");
    }
  };
  correctBtn.addEventListener("click", () => mark("correct"));
  incorrectBtn.addEventListener("click", () => mark("incorrect"));
  let timer = null;
  noteEl.addEventListener("input", () => {
    // Persist note edits for an already-incorrect row without re-marking.
    if (r.flag?.state !== "incorrect") return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      fetch("/api/flag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: r.id, state: "incorrect", note: noteEl.value }),
      });
    }, 600);
  });

  return div;
}

let metaCache = null;
function refreshCounts(deltaState) {
  if (!metaCache) return;
  metaCache.reviewed[deltaState] += 1;
  metaCache.reviewed.unreviewed = Math.max(0, metaCache.reviewed.unreviewed - 1);
  paintSummary();
}

function paintSummary() {
  const m = metaCache;
  const r = m.reviewed;
  el("summary").textContent =
    `${m.total.toLocaleString()} comments · live-regex extractions · ` +
    `${r.unreviewed.toLocaleString()} unreviewed · ${r.correct.toLocaleString()} correct · ` +
    `${r.incorrect.toLocaleString()} incorrect · built ${new Date(m.built_at).toLocaleString()}`;
}

async function loadMeta() {
  metaCache = await (await fetch("/api/meta")).json();
  paintSummary();
  const site = el("site");
  site.length = 1;
  for (const s of metaCache.sites) {
    const opt = document.createElement("option");
    opt.value = s.site;
    opt.textContent = `${s.site} (${s.count})`;
    site.appendChild(opt);
  }
}

async function loadQueue() {
  const params = new URLSearchParams({
    status: state.status,
    site: state.site,
    minSuspicion: state.minSuspicion,
    commented: state.commented,
    q: state.q,
  });
  listEl.innerHTML = '<div class="empty-state">Loading…</div>';
  const data = await (await fetch(`/api/queue?${params}`)).json();
  state.queue = data.ids;
  state.cursor = 0;
  state.markedThisSession.clear();
  renderPage();
}

async function renderPage() {
  // Walk forward from cursor, skipping ids marked this session, until we have a
  // page worth of still-visible ids (or run out).
  const ids = [];
  let i = state.cursor;
  while (i < state.queue.length && ids.length < state.pageSize) {
    const id = state.queue[i];
    if (!state.markedThisSession.has(id)) ids.push(id);
    i += 1;
  }
  state.pageEnd = i;
  listEl.innerHTML = "";
  if (!ids.length) {
    listEl.innerHTML = state.queue.length
      ? '<div class="empty-state">Done — nothing left in this view. Use the status filter to revisit reviewed rows.</div>'
      : '<div class="empty-state">No rows match these filters.</div>';
  } else {
    const data = await (await fetch("/api/rows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    })).json();
    for (const r of data.rows) listEl.appendChild(card(r));
  }
  const shown = Math.min(state.cursor + state.pageSize, state.queue.length);
  el("pageInfo").textContent = state.queue.length
    ? `${(state.cursor + 1).toLocaleString()}–${shown.toLocaleString()} of ${state.queue.length.toLocaleString()}`
    : "0 of 0";
  el("prev").disabled = state.cursor === 0;
  el("next").disabled = state.pageEnd >= state.queue.length;
  window.scrollTo({ top: 0 });
}

el("status").addEventListener("change", (e) => { state.status = e.target.value; loadQueue(); });
el("site").addEventListener("change", (e) => { state.site = e.target.value; loadQueue(); });
el("minSuspicion").addEventListener("change", (e) => { state.minSuspicion = e.target.value; loadQueue(); });
el("commented").addEventListener("change", (e) => { state.commented = e.target.value; loadQueue(); });
let qTimer = null;
el("q").addEventListener("input", (e) => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { state.q = e.target.value; loadQueue(); }, 350);
});
el("prev").addEventListener("click", () => {
  state.cursor = Math.max(0, state.cursor - state.pageSize);
  renderPage();
});
el("next").addEventListener("click", () => {
  if (state.pageEnd < state.queue.length) { state.cursor = state.pageEnd; renderPage(); }
});
el("export").addEventListener("click", async (e) => {
  const btn = e.target;
  btn.disabled = true;
  try {
    const data = await (await fetch("/api/export")).json();
    alert(`Exported ${data.count} flagged-incorrect comments to:\n${data.path}\n\n(also saved as flagged_extractions.latest.json)`);
  } catch (err) {
    alert("Export failed: " + err);
  } finally {
    btn.disabled = false;
  }
});

loadMeta().then(loadQueue);
