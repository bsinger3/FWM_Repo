const bundle = window.FWM_MOBILE_BUNDLE;
const storageKey = `fwm-mobile-review-${bundle?.storageNamespace || bundle?.bundleId || "unknown"}`;
const reviewedStorageKey = `${storageKey}-reviewed`;
const progressHashPrefix = "fwmprogress=";

const state = {
  activeBucket: "all",
  activeBatch: "all",
  clickMode: "inspect",
  viewMode: "swipe",
  rows: bundle?.rows || [],
  dirty: new Map(),
  reviewed: new Map(),
  swipeIndex: 0,
  swipeHistory: [],
  swipeDrag: null,
  suppressTapUntil: 0,
  unsavedLocalChanges: 0,
  legendFilter: "",
  duplicateGroups: new Map(),
  exportInProgress: false,
  bulkActionInProgress: false,
  localSaveAvailable: true,
};

const localSaveBatchSize = 1;

const el = {
  summary: document.getElementById("bundle-summary"),
  exportBtn: document.getElementById("export-btn"),
  importBtn: document.getElementById("import-btn"),
  importFile: document.getElementById("import-file"),
  bucketSelect: document.getElementById("bucket-select"),
  batchSelect: document.getElementById("batch-select"),
  reasonFilter: document.getElementById("reason-filter"),
  stateFilter: document.getElementById("state-filter"),
  rejectReason: document.getElementById("reject-reason"),
  viewModeGrid: document.getElementById("view-mode-grid"),
  viewModeSwipe: document.getElementById("view-mode-swipe"),
  hideDuplicates: document.getElementById("hide-duplicates"),
  showReasons: document.getElementById("show-reasons"),
  approveVisible: document.getElementById("approve-visible"),
  rejectVisible: document.getElementById("reject-visible"),
  status: document.getElementById("status"),
  legend: document.getElementById("legend"),
  swipeView: document.getElementById("swipe-view"),
  swipeCounter: document.getElementById("swipe-counter"),
  swipeState: document.getElementById("swipe-state"),
  swipeDeck: document.getElementById("swipe-deck"),
  swipeReject: document.getElementById("swipe-reject"),
  swipeUndo: document.getElementById("swipe-undo"),
  swipeSkip: document.getElementById("swipe-skip"),
  swipeApprove: document.getElementById("swipe-approve"),
  grid: document.getElementById("grid"),
  dialog: document.getElementById("detail-dialog"),
  detailImage: document.getElementById("detail-image"),
  detailTitle: document.getElementById("detail-title"),
  detailSubtitle: document.getElementById("detail-subtitle"),
  detailApprove: document.getElementById("detail-approve"),
  detailReject: document.getElementById("detail-reject"),
  detailNeutral: document.getElementById("detail-neutral"),
  detailRejectReason: document.getElementById("detail-reject-reason"),
  detailNotes: document.getElementById("detail-notes"),
  detailSave: document.getElementById("detail-save"),
  detailMeta: document.getElementById("detail-meta"),
  topBtn: document.getElementById("top-btn"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function rowDecisionKey(row) {
  return `${row.bucket}::${row.partFile}::${row.rowKey}`;
}

function compactDecisionForStorage(decision) {
  return {
    humanState: decision.humanState || "NEUTRAL",
    rejectionReason: decision.rejectionReason || "",
    reviewNotes: decision.reviewNotes || "",
  };
}

function decisionStateCode(humanState) {
  if (humanState === "APPROVE") return "A";
  if (humanState === "DISAPPROVE") return "R";
  return "N";
}

function humanStateFromCode(code) {
  if (code === "A") return "APPROVE";
  if (code === "R") return "DISAPPROVE";
  return "NEUTRAL";
}

function encodeHashJson(value) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(value))));
}

function decodeHashJson(value) {
  return JSON.parse(decodeURIComponent(escape(atob(value))));
}

function rowsByDecisionKey() {
  return new Map(state.rows.map((row, index) => [rowDecisionKey(row), { row, index }]));
}

function updateProgressHash() {
  const rowIndex = rowsByDecisionKey();
  const progress = [];
  for (const [key, decision] of state.dirty.entries()) {
    const item = rowIndex.get(key);
    if (!item) continue;
    const compact = compactDecisionForStorage(decision);
    progress.push([
      item.index,
      decisionStateCode(compact.humanState),
      compact.rejectionReason,
      compact.reviewNotes,
    ]);
  }
  const url = new URL(window.location.href);
  if (progress.length) {
    url.hash = `${progressHashPrefix}${encodeHashJson(progress)}`;
  } else {
    url.hash = "";
  }
  try {
    window.history.replaceState(null, "", url.toString());
  } catch (error) {
    console.warn("Could not update URL progress backup", error);
  }
}

function loadHashProgress() {
  const decisions = new Map();
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash.startsWith(progressHashPrefix)) return decisions;
  try {
    const progress = decodeHashJson(hash.slice(progressHashPrefix.length));
    if (!Array.isArray(progress)) return decisions;
    for (const item of progress) {
      if (!Array.isArray(item)) continue;
      const [index, stateCode, rejectionReason = "", reviewNotes = ""] = item;
      const row = state.rows[index];
      if (!row) continue;
      decisions.set(
        rowDecisionKey(row),
        buildDecision(row, {
          humanState: humanStateFromCode(stateCode),
          rejectionReason,
          reviewNotes,
        }),
      );
    }
  } catch (error) {
    console.warn("Could not load URL progress backup", error);
  }
  return decisions;
}

function loadStoredDecisionMap(key) {
  const decisions = new Map();
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return decisions;
    const rowsByKey = new Map(state.rows.map((row) => [rowDecisionKey(row), row]));
    for (const [key, value] of Object.entries(JSON.parse(raw))) {
      const row = rowsByKey.get(key);
      decisions.set(key, row ? buildDecision(row, value || {}) : value);
    }
  } catch (error) {
    console.warn("Could not load phone review progress", error);
  }
  return decisions;
}

function loadSavedProgress() {
  state.reviewed = loadStoredDecisionMap(reviewedStorageKey);
  state.dirty = loadStoredDecisionMap(storageKey);
  for (const [key, decision] of loadHashProgress().entries()) {
    state.dirty.set(key, decision);
  }
}

function persistDecisionMap(key, decisions) {
  const compactDecisions = {};
  for (const [decisionKey, decision] of decisions.entries()) {
    compactDecisions[decisionKey] = compactDecisionForStorage(decision);
  }
  localStorage.removeItem(key);
  localStorage.setItem(key, JSON.stringify(compactDecisions));
}

function persistReviewed() {
  try {
    persistDecisionMap(reviewedStorageKey, state.reviewed);
    updateProgressHash();
    return true;
  } catch (error) {
    console.warn("Could not save exported phone review progress", error);
    return false;
  }
}

function persistDirty() {
  try {
    persistDecisionMap(storageKey, state.dirty);
    updateProgressHash();
    state.unsavedLocalChanges = 0;
    state.localSaveAvailable = true;
    return true;
  } catch (error) {
    updateProgressHash();
    state.unsavedLocalChanges = 0;
    state.localSaveAvailable = false;
    console.warn("Could not autosave phone review progress", error);
    return false;
  }
}

function maybePersistDirty() {
  state.unsavedLocalChanges += 1;
  if (state.unsavedLocalChanges >= localSaveBatchSize) {
    persistDirty();
  }
}

function getRowDecision(row) {
  return {
    ...row,
    humanState: "NEUTRAL",
    rejectionReason: "",
    reviewNotes: "",
    ...(state.reviewed.get(rowDecisionKey(row)) || {}),
    ...(state.dirty.get(rowDecisionKey(row)) || {}),
  };
}

function buildDecision(row, patch) {
  const current = getRowDecision(row);
  const humanState = patch.humanState ?? current.humanState ?? "NEUTRAL";
  return {
    bucket: row.bucket,
    partFile: row.partFile,
    rowKey: row.rowKey,
    sourceFile: row.sourceFile || "",
    sourceRowNumber: row.sourceRowNumber || "",
    defaultDecision: row.defaultDecision || "",
    cvDecision: row.cvDecision || "",
    cvReasonCode: row.cvReasonCode || "",
    cvReasonSummary: row.cvReasonSummary || "",
    sorterRecommendation: row.sorterRecommendation || "",
    sorterReasonCodes: row.sorterReasonCodes || "",
    humanState,
    rejectionReason: humanState === "DISAPPROVE" ? patch.rejectionReason ?? current.rejectionReason ?? "" : "",
    reviewNotes: patch.reviewNotes ?? current.reviewNotes ?? "",
  };
}

function duplicateImageKey(row) {
  const raw = String(row.imageUrl || row.rawImageUrl || row.imagePath || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    url.hash = "";
    url.search = "";
    url.pathname = url.pathname.replace(/\._[^/.]+_\.(jpe?g|png|webp)$/i, ".$1");
    return url.toString().toLowerCase();
  } catch {
    return raw.replace(/\?.*$/, "").replace(/\._[^/.]+_\.(jpe?g|png|webp)$/i, ".$1").toLowerCase();
  }
}

function rebuildDuplicateGroups() {
  state.duplicateGroups = new Map();
  for (const row of state.rows) {
    const key = duplicateImageKey(row);
    if (!key) continue;
    if (!state.duplicateGroups.has(key)) state.duplicateGroups.set(key, []);
    state.duplicateGroups.get(key).push(row);
  }
}

function rowsForReviewUnit(row) {
  if (!el.hideDuplicates.checked) return [row];
  const key = duplicateImageKey(row);
  if (!key) return [row];
  return state.duplicateGroups.get(key) || [row];
}

function setRowDecision(row, patch) {
  for (const target of rowsForReviewUnit(row)) {
    state.dirty.set(rowDecisionKey(target), buildDecision(target, patch));
  }
  maybePersistDirty();
  render();
}

function setRowDecisionQuiet(row, patch) {
  for (const target of rowsForReviewUnit(row)) {
    state.dirty.set(rowDecisionKey(target), buildDecision(target, patch));
  }
  maybePersistDirty();
}

function shortReason(reason) {
  if (!reason) return "";
  return String(reason)
    .replace(/^BORDERLINE_/, "BORDERLINE ")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function reasonColor(reason) {
  const value = String(reason || "").toUpperCase();
  if (value.includes("BODY") || value.includes("GARMENT") || value.includes("COVERAGE")) return "#2563eb";
  if (value.includes("MULTIPLE") || value.includes("AMBIGUOUS")) return "#7c3aed";
  if (value.includes("NO_PERSON") || value.includes("NOT_WORN")) return "#64748b";
  if (value.includes("FETCH") || value.includes("RESOLUTION") || value.includes("DARK") || value.includes("BLUR")) return "#b7791f";
  if (value.includes("WRONG") || value.includes("CONTEXT")) return "#c2410c";
  if (value.includes("DUPLICATE")) return "#0f766e";
  return "#667085";
}

function reasonForRow(row) {
  const decision = getRowDecision(row);
  return decision.rejectionReason || row.cvReasonCode || row.sorterReasonCodes || row.defaultDecision || row.bucket;
}

function formatHeight(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "";
  return `${Math.floor(n / 12)}'${Math.round(n % 12)}"`;
}

function formatWeight(value) {
  if (!value) return "";
  const raw = String(value).trim();
  const range = raw.match(/\b(\d{2,3}(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)?\b/i);
  if (range) return `${range[1]}-${range[2]} lb`;
  const n = Number.parseFloat(raw.replace(/[^0-9.]+/g, ""));
  if (!Number.isFinite(n)) return raw;
  return `${Number.isInteger(n) ? n : n.toFixed(1).replace(/\.0$/, "")} lb`;
}

function requireRejectReason() {
  return true;
}

function applyClickMode(row) {
  const current = getRowDecision(row);
  if (state.clickMode === "approve") {
    setRowDecision(row, { humanState: current.humanState === "APPROVE" ? "NEUTRAL" : "APPROVE" });
    return true;
  }
  if (state.clickMode === "reject") {
    setRowDecision(row, {
      humanState: current.humanState === "DISAPPROVE" ? "NEUTRAL" : "DISAPPROVE",
      rejectionReason: el.rejectReason.value,
    });
    return true;
  }
  return false;
}

function passesFilters(row) {
  if (state.activeBucket !== "all" && row.bucket !== state.activeBucket) return false;
  if (state.activeBatch !== "all" && String(row.batchNumber || 1) !== state.activeBatch) return false;
  const decision = getRowDecision(row);
  if (el.stateFilter.value === "dirty" && !state.dirty.has(rowDecisionKey(row))) return false;
  if (["NEUTRAL", "APPROVE", "DISAPPROVE"].includes(el.stateFilter.value) && decision.humanState !== el.stateFilter.value) return false;
  const reason = state.legendFilter || el.reasonFilter.value;
  if (reason && ![decision.rejectionReason, row.cvReasonCode, row.sorterReasonCodes, row.defaultDecision].includes(reason)) return false;
  return true;
}

function filteredRows() {
  const rows = state.rows.filter(passesFilters);
  if (!el.hideDuplicates.checked) return rows;
  const seen = new Set();
  return rows.filter((row) => {
    const key = duplicateImageKey(row);
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function pill(value, className = "") {
  if (!value) return "";
  return `<span class="pill ${className}">${escapeHtml(value)}</span>`;
}

function renderCard(row) {
  const decision = getRowDecision(row);
  const card = document.createElement("article");
  const stateClass = decision.humanState === "APPROVE" ? "approved" : decision.humanState === "DISAPPROVE" ? "rejected" : "";
  card.className = ["card", "quick-grid-card", stateClass].filter(Boolean).join(" ");
  const duplicateCount = rowsForReviewUnit(row).length;
  const reason = reasonForRow(row);
  const bra = row.braBandIn && row.cupSize ? `${row.braBandIn}${row.cupSize}` : row.bustIn ? `${row.bustIn}" bust` : "";
  const imageMarkup = row.imagePath
    ? `<img src="${escapeHtml(row.imagePath)}" alt="" loading="lazy" />`
    : `<div class="missing-image">Image not downloaded</div>`;
  card.innerHTML = `
    ${duplicateCount > 1 ? `<span class="dup">x${duplicateCount}</span>` : ""}
    ${imageMarkup}
    <div class="card-meta">
      <div class="meta-row">
        ${pill(formatHeight(row.heightIn))}
        ${pill(formatWeight(row.weightLbs))}
        ${pill(bra)}
        ${pill(row.waistIn ? `Waist ${row.waistIn}"` : "")}
        ${pill(row.hipsIn ? `Hips ${row.hipsIn}"` : "")}
      </div>
      <div class="meta-row">
        ${el.showReasons.checked ? pill(shortReason(reason), "reason-pill", reason) : ""}
        ${decision.reviewNotes ? pill("Note") : ""}
      </div>
    </div>
    <div class="actions">
      <button type="button" class="approve ${decision.humanState === "APPROVE" ? "active" : ""}">A</button>
      <button type="button" class="reject ${decision.humanState === "DISAPPROVE" ? "active" : ""}">R</button>
      <button type="button" class="neutral">N</button>
      <button type="button" class="detail">i</button>
    </div>
  `;
  const reasonPill = card.querySelector(".reason-pill");
  if (reasonPill) reasonPill.style.setProperty("--reason-color", reasonColor(reason));
  card.addEventListener("click", (event) => {
    if (event.target.closest(".approve")) {
      setRowDecision(row, { humanState: decision.humanState === "APPROVE" ? "NEUTRAL" : "APPROVE" });
      return;
    }
    if (event.target.closest(".reject")) {
      setRowDecision(row, {
        humanState: decision.humanState === "DISAPPROVE" ? "NEUTRAL" : "DISAPPROVE",
        rejectionReason: el.rejectReason.value,
      });
      return;
    }
    if (event.target.closest(".neutral")) {
      setRowDecision(row, { humanState: "NEUTRAL" });
      return;
    }
    if (event.target.closest(".detail")) {
      openDetail(row);
      return;
    }
    if (applyClickMode(row)) return;
    setRowDecision(row, { humanState: decision.humanState === "APPROVE" ? "NEUTRAL" : "APPROVE" });
  });
  return card;
}

function renderLegend(rows) {
  const counts = new Map();
  for (const row of rows) {
    const reason = reasonForRow(row);
    counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  el.legend.textContent = "";
  for (const [reason, count] of Array.from(counts.entries()).sort((a, b) => b[1] - a[1])) {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `<span class="swatch"></span><span>${escapeHtml(shortReason(reason))}</span><strong>${count}</strong>`;
    button.querySelector(".swatch").style.setProperty("--reason-color", reasonColor(reason));
    button.addEventListener("click", () => {
      state.legendFilter = state.legendFilter === reason ? "" : reason;
      render();
    });
    el.legend.appendChild(button);
  }
}

function render() {
  const rows = filteredRows();
  document.body.classList.toggle("mode-swipe", state.viewMode === "swipe");
  document.body.classList.toggle("mode-grid", state.viewMode === "grid");
  if (state.viewMode === "grid") {
    el.grid.hidden = false;
    el.swipeView.hidden = true;
    el.grid.textContent = "";
    const fragment = document.createDocumentFragment();
    for (const row of rows) fragment.appendChild(renderCard(row));
    el.grid.appendChild(fragment);
  } else {
    el.grid.hidden = true;
    el.swipeView.hidden = false;
    renderSwipeView(rows);
  }
  renderLegend(rows);
  el.status.textContent = `${rows.length} visible | ${state.dirty.size} changed`;
}

function setViewMode(mode) {
  state.viewMode = mode;
  state.swipeIndex = Math.min(state.swipeIndex, Math.max(filteredRows().length - 1, 0));
  el.viewModeGrid.classList.toggle("active", mode === "grid");
  el.viewModeSwipe.classList.toggle("active", mode === "swipe");
  render();
}

function undecidedSwipeRows(rows = filteredRows()) {
  return rows.filter((row) => getRowDecision(row).humanState === "NEUTRAL");
}

function renderSwipeView(rows) {
  const deckRows = undecidedSwipeRows(rows);
  state.swipeIndex = Math.min(state.swipeIndex, Math.max(deckRows.length - 1, 0));
  const row = deckRows[state.swipeIndex];
  el.swipeDeck.textContent = "";
  el.swipeCounter.textContent = deckRows.length ? `${state.swipeIndex + 1} / ${deckRows.length}` : "0 / 0";
  el.swipeState.textContent = deckRows.length ? "Swipe right approve, left reject, tap for details" : "No neutral cards in this view";
  el.swipeUndo.disabled = state.swipeHistory.length === 0;
  for (const button of [el.swipeApprove, el.swipeReject, el.swipeSkip]) button.disabled = !row;
  if (!row) {
    const empty = document.createElement("div");
    empty.className = "swipe-empty";
    empty.textContent = "No cards left in this view.";
    el.swipeDeck.appendChild(empty);
    return;
  }
  el.swipeDeck.appendChild(renderSwipeCard(row));
}

function renderSwipeCard(row) {
  const card = document.createElement("article");
  card.className = "swipe-card";
  const reason = reasonForRow(row);
  const bra = row.braBandIn && row.cupSize ? `${row.braBandIn}${row.cupSize}` : row.bustIn ? `${row.bustIn}" bust` : "";
  card.innerHTML = `
    <div class="swipe-stamp approve-stamp">Approve</div>
    <div class="swipe-stamp reject-stamp">Reject</div>
    ${row.imagePath ? `<img src="${escapeHtml(row.imagePath)}" alt="" />` : `<div class="missing-image">Image not downloaded</div>`}
    <div class="swipe-meta">
      <div class="meta-row">
        ${pill(formatHeight(row.heightIn))}
        ${pill(formatWeight(row.weightLbs))}
        ${pill(bra)}
        ${pill(row.waistIn ? `Waist ${row.waistIn}"` : "")}
        ${pill(row.hipsIn ? `Hips ${row.hipsIn}"` : "")}
      </div>
      <div class="meta-row">
        ${pill(shortReason(reason), "reason-pill")}
      </div>
    </div>
  `;
  const reasonPill = card.querySelector(".reason-pill");
  if (reasonPill) reasonPill.style.setProperty("--reason-color", reasonColor(reason));
  bindSwipeCard(card, row);
  return card;
}

function bindSwipeCard(card, row) {
  card.addEventListener("pointerdown", (event) => {
    card.setPointerCapture?.(event.pointerId);
    state.swipeDrag = {
      row,
      startX: event.clientX,
      startY: event.clientY,
      x: event.clientX,
      y: event.clientY,
      moved: false,
    };
    card.classList.add("dragging");
  });
  card.addEventListener("pointermove", (event) => {
    if (!state.swipeDrag || state.swipeDrag.row !== row) return;
    const drag = state.swipeDrag;
    drag.x = event.clientX;
    drag.y = event.clientY;
    const dx = drag.x - drag.startX;
    const dy = drag.y - drag.startY;
    drag.moved = Math.abs(dx) > 8 || Math.abs(dy) > 8;
    const rotation = Math.max(-12, Math.min(12, dx / 18));
    card.style.transform = `translate(${dx}px, ${dy}px) rotate(${rotation}deg)`;
    card.classList.toggle("swiping-approve", dx > 48);
    card.classList.toggle("swiping-reject", dx < -48);
  });
  card.addEventListener("pointerup", () => finishSwipeDrag(card, row));
  card.addEventListener("pointercancel", () => resetSwipeCard(card));
  card.addEventListener("click", () => {
    if (Date.now() < state.suppressTapUntil) return;
    if (state.swipeDrag?.moved) return;
    openDetail(row);
  });
}

function finishSwipeDrag(card, row) {
  const drag = state.swipeDrag;
  if (!drag || drag.row !== row) return;
  const dx = drag.x - drag.startX;
  const dy = drag.y - drag.startY;
  state.swipeDrag = null;
  card.classList.remove("dragging");
  if (Math.abs(dx) < 96 || Math.abs(dx) < Math.abs(dy) * 1.2) {
    resetSwipeCard(card);
    return;
  }
  state.suppressTapUntil = Date.now() + 350;
  commitSwipe(row, dx > 0 ? "APPROVE" : "DISAPPROVE");
}

function resetSwipeCard(card) {
  state.swipeDrag = null;
  card.classList.remove("dragging", "swiping-approve", "swiping-reject");
  card.style.transform = "";
}

function commitSwipe(row, humanState) {
  const before = state.dirty.get(rowDecisionKey(row)) || null;
  state.swipeHistory.push({ row, before });
  setRowDecisionQuiet(row, {
    humanState,
    rejectionReason: humanState === "DISAPPROVE" ? el.rejectReason.value : "",
  });
  const remaining = undecidedSwipeRows();
  state.swipeIndex = Math.min(state.swipeIndex, Math.max(remaining.length - 1, 0));
  render();
}

function skipSwipe() {
  const rows = undecidedSwipeRows();
  if (!rows.length) return;
  state.swipeIndex = (state.swipeIndex + 1) % rows.length;
  render();
}

function undoSwipe() {
  const item = state.swipeHistory.pop();
  if (!item) return;
  const key = rowDecisionKey(item.row);
  if (item.before) state.dirty.set(key, item.before);
  else state.dirty.delete(key);
  maybePersistDirty();
  const rows = undecidedSwipeRows();
  const restoredIndex = rows.findIndex((row) => rowDecisionKey(row) === rowDecisionKey(item.row));
  state.swipeIndex = restoredIndex >= 0 ? restoredIndex : 0;
  render();
}

function renderBucketSelect() {
  const buckets = ["all", ...new Set(state.rows.map((row) => row.bucket))];
  el.bucketSelect.textContent = "";
  for (const bucket of buckets) {
    const option = document.createElement("option");
    option.value = bucket;
    option.textContent = bucket === "all" ? "All sets" : shortReason(bucket).replace(" Candidates", "");
    option.selected = bucket === state.activeBucket;
    el.bucketSelect.appendChild(option);
  }
}

function renderBatchSelect() {
  const batchRows = state.activeBucket === "all"
    ? state.rows
    : state.rows.filter((row) => row.bucket === state.activeBucket);
  const batches = Array.from(
    batchRows.reduce((map, row) => {
      const batchNumber = String(row.batchNumber || 1);
      map.set(batchNumber, (map.get(batchNumber) || 0) + 1);
      return map;
    }, new Map()).entries(),
  ).sort((a, b) => Number(a[0]) - Number(b[0]));

  el.batchSelect.textContent = "";
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "All";
  all.selected = state.activeBatch === "all";
  el.batchSelect.appendChild(all);
  for (const [batchNumber, count] of batches) {
    const option = document.createElement("option");
    option.value = batchNumber;
    option.textContent = `B${batchNumber} (${count})`;
    option.selected = state.activeBatch === batchNumber;
    el.batchSelect.appendChild(option);
  }
  if (state.activeBatch !== "all" && !batches.some(([batchNumber]) => batchNumber === state.activeBatch)) {
    state.activeBatch = "all";
    all.selected = true;
  }
}

function fillSelects() {
  const reasons = Array.from(new Set([...(bundle.rejectionReasons || []), ...state.rows.flatMap((row) => [row.cvReasonCode, row.sorterReasonCodes]).filter(Boolean)])).sort();
  el.reasonFilter.innerHTML = `<option value="">All reasons</option>${reasons.map((reason) => `<option value="${escapeHtml(reason)}">${escapeHtml(shortReason(reason))}</option>`).join("")}`;
  const rejectOptions = (bundle.rejectionReasons || []).map((reason) => `<option value="${escapeHtml(reason)}">${escapeHtml(shortReason(reason))}</option>`).join("");
  el.rejectReason.innerHTML = rejectOptions;
  el.detailRejectReason.innerHTML = `<option value="">No reason selected</option>${rejectOptions}`;
}

function openDetail(row) {
  const decision = getRowDecision(row);
  el.detailImage.src = row.imagePath || row.imageUrl || "";
  el.detailTitle.textContent = row.productTitle || row.clothingType || "Review image";
  el.detailSubtitle.textContent = `${shortReason(reasonForRow(row))} | ${row.rowKey}`;
  el.detailRejectReason.value = decision.rejectionReason || "";
  el.detailNotes.value = decision.reviewNotes || "";
  const fields = [
    ["State", decision.humanState],
    ["Reject reason", shortReason(decision.rejectionReason)],
    ["Comment", decision.reviewNotes],
    ["Size", row.size],
    ["Height", formatHeight(row.heightIn)],
    ["Weight", formatWeight(row.weightLbs)],
    ["Bra/bust", row.braBandIn && row.cupSize ? `${row.braBandIn}${row.cupSize}` : row.bustIn],
    ["Waist", row.waistIn],
    ["Hips", row.hipsIn],
    ["CV reason", shortReason(row.cvReasonCode)],
    ["CV summary", row.cvReasonSummary],
    ["Sorter reasons", row.sorterReasonCodes],
    ["User comment", row.userComment],
    ["Source file", row.sourceFile],
    ["Source row", row.sourceRowNumber],
  ];
  el.detailMeta.innerHTML = fields.filter(([, value]) => value).map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("");
  el.detailApprove.onclick = () => applyDetailDecision(row, { humanState: "APPROVE" });
  el.detailReject.onclick = () => applyDetailDecision(row, {
    humanState: "DISAPPROVE",
    rejectionReason: el.detailRejectReason.value,
  });
  el.detailNeutral.onclick = () => applyDetailDecision(row, { humanState: "NEUTRAL" });
  el.detailSave.onclick = () => applyDetailDecision(row, {
    rejectionReason: el.detailRejectReason.value,
  });
  el.dialog.showModal();
}

function applyDetailDecision(row, patch) {
  setRowDecisionQuiet(row, {
    ...patch,
    reviewNotes: el.detailNotes.value,
  });
  el.dialog.close();
  if (state.viewMode === "swipe") {
    const rows = undecidedSwipeRows();
    state.swipeIndex = Math.min(state.swipeIndex, Math.max(rows.length - 1, 0));
  }
  render();
}

function setClickMode(mode) {
  state.clickMode = mode;
  document.querySelectorAll("[data-click-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.clickMode === mode);
  });
}

function visibleUnmarkedRows() {
  return filteredRows().filter((row) => getRowDecision(row).humanState === "NEUTRAL");
}

function nextFrame() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}

async function applyVisible(patch) {
  if (state.bulkActionInProgress) return;
  state.bulkActionInProgress = true;
  const previousApproveDisabled = el.approveVisible.disabled;
  const previousRejectDisabled = el.rejectVisible.disabled;
  el.approveVisible.disabled = true;
  el.rejectVisible.disabled = true;
  const rows = visibleUnmarkedRows();
  el.status.textContent = `Marking ${rows.length} visible card(s)...`;
  try {
    await nextFrame();
    for (const row of rows) {
      const targets = [...rowsForReviewUnit(row)];
      for (const target of targets) {
        state.dirty.set(rowDecisionKey(target), buildDecision(target, patch));
      }
    }
    persistDirty();
    render();
  } finally {
    state.bulkActionInProgress = false;
    el.approveVisible.disabled = previousApproveDisabled;
    el.rejectVisible.disabled = previousRejectDisabled;
  }
}

function showUnreviewedOnly() {
  el.stateFilter.value = "NEUTRAL";
  state.legendFilter = "";
  state.swipeIndex = 0;
  window.scrollTo({ top: 0, behavior: "smooth" });
  render();
}

function importDecisionPayload(payload) {
  const decisions = Array.isArray(payload?.decisions) ? payload.decisions : [];
  if (!decisions.length) {
    throw new Error("No decisions were found in that JSON file.");
  }
  const rowIndex = rowsByDecisionKey();
  let imported = 0;
  let ignored = 0;
  for (const decision of decisions) {
    const key = decisionKeyFromDecision(decision);
    const item = key ? rowIndex.get(key) : null;
    if (!item) {
      ignored += 1;
      continue;
    }
    state.dirty.set(key, buildDecision(item.row, decision));
    imported += 1;
  }
  persistDirty();
  showUnreviewedOnly();
  return { imported, ignored };
}

async function importProgressFiles(files) {
  const selectedFiles = Array.from(files || []);
  if (!selectedFiles.length) return;
  let imported = 0;
  let ignored = 0;
  const failures = [];
  try {
    for (const file of selectedFiles) {
      try {
        const payload = JSON.parse(await file.text());
        const result = importDecisionPayload(payload);
        imported += result.imported;
        ignored += result.ignored;
      } catch (error) {
        failures.push(`${file.name}: ${error.message || error}`);
      }
    }
    const message = `Imported ${imported} decision(s). ${ignored} were for other files/batches.`;
    alert(failures.length ? `${message}\n\nCould not read:\n${failures.join("\n")}` : message);
  } finally {
    el.importFile.value = "";
  }
}

function markExportedDecisionsReviewed(decisions) {
  for (const decision of decisions) {
    if (!["APPROVE", "DISAPPROVE"].includes(decision.humanState)) continue;
    const key = decisionKeyFromDecision(decision);
    if (!key) continue;
    state.reviewed.set(key, decision);
  }
  persistReviewed();
}

function decisionKeyFromDecision(decision) {
  const bucket = decision.bucket || "";
  const partFile = decision.partFile || decision.part_file || "";
  const rowKey = decision.rowKey || decision.review_row_key || "";
  return bucket && partFile && rowKey ? `${bucket}::${partFile}::${rowKey}` : "";
}

function safeFilenamePart(value) {
  return String(value || "")
    .trim()
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
}

function currentReviewFileLabel() {
  const pathLabel = safeFilenamePart(window.location.pathname.split("/").pop());
  if (pathLabel) return pathLabel;
  const batch = bundle?.splitBatch?.batchNumber ? `file_${String(bundle.splitBatch.batchNumber).padStart(2, "0")}` : "";
  return safeFilenamePart(`${bundle?.bundleId || "mobile_review"}_${batch}`);
}

async function exportDecisions() {
  if (state.exportInProgress) return;
  state.exportInProgress = true;
  el.exportBtn.disabled = true;
  const previousLabel = el.exportBtn.textContent;
  el.exportBtn.textContent = "Exporting";
  try {
    persistDirty();
    const decisions = Array.from(state.dirty.values());
    const exportedAt = new Date().toISOString();
    const payload = {
      format: "fwm-mobile-image-review-decisions-v1",
      bundleId: bundle.bundleId,
      generatedAt: bundle.generatedAt,
      exportedAt,
      parts: bundle.parts,
      decisions,
    };
    const exported = await saveDecisionPayload(payload);
    if (exported) {
      markExportedDecisionsReviewed(decisions);
      showUnreviewedOnly();
    }
  } catch (error) {
    alert(`Could not export decisions: ${error.message || error}`);
  } finally {
    state.exportInProgress = false;
    el.exportBtn.disabled = false;
    el.exportBtn.textContent = previousLabel;
  }
}

async function saveDecisionPayload(payload) {
  const exportedAt = payload.exportedAt;
  const stamp = exportedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const filename = `fwm_mobile_review_${currentReviewFileLabel()}_${stamp}.json`;
  const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], { type: "application/json" });

  const isAndroidChrome = /Android/i.test(navigator.userAgent || "");
  if (!isAndroidChrome && "showSaveFilePicker" in window) {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [
          {
            description: "FWM mobile review decisions",
            accept: { "application/json": [".json"] },
          },
        ],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      alert(`Saved ${payload.decisions.length} decision(s) to ${filename}.`);
      return true;
    } catch (error) {
      if (error?.name !== "AbortError") {
        console.warn("Save picker failed, falling back to download", error);
      } else {
        return false;
      }
    }
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
    link.remove();
  }, 30000);
  alert(
    `Downloaded ${payload.decisions.length} decision(s) to ${filename}.\n\nMove it to BrisApps/FWM_Image_Review/returns_to_laptop before copying it back to the Mac.`,
  );
  return true;
}

function bindEvents() {
  for (const input of [el.reasonFilter, el.stateFilter, el.hideDuplicates, el.showReasons]) {
    input.addEventListener("input", () => {
      if (input === el.reasonFilter) state.legendFilter = "";
      render();
    });
  }
  el.bucketSelect.addEventListener("input", () => {
    state.activeBucket = el.bucketSelect.value;
    state.activeBatch = "all";
    state.swipeIndex = 0;
    renderBatchSelect();
    render();
  });
  el.batchSelect.addEventListener("input", () => {
    state.activeBatch = el.batchSelect.value;
    state.swipeIndex = 0;
    render();
  });
  document.querySelectorAll("[data-click-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      setClickMode(button.dataset.clickMode);
    });
  });
  el.viewModeGrid.addEventListener("click", () => setViewMode("grid"));
  el.viewModeSwipe.addEventListener("click", () => setViewMode("swipe"));
  el.approveVisible.addEventListener("click", () => {
    applyVisible({ humanState: "APPROVE" }).catch((error) => {
      alert(`Could not approve visible cards: ${error.message || error}`);
    });
  });
  el.rejectVisible.addEventListener("click", () => {
    applyVisible({ humanState: "DISAPPROVE", rejectionReason: el.rejectReason.value }).catch((error) => {
      alert(`Could not reject visible cards: ${error.message || error}`);
    });
  });
  el.swipeApprove.addEventListener("click", () => {
    const row = undecidedSwipeRows()[state.swipeIndex];
    if (row) commitSwipe(row, "APPROVE");
  });
  el.swipeReject.addEventListener("click", () => {
    const row = undecidedSwipeRows()[state.swipeIndex];
    if (row) commitSwipe(row, "DISAPPROVE");
  });
  el.swipeSkip.addEventListener("click", skipSwipe);
  el.swipeUndo.addEventListener("click", undoSwipe);
  el.exportBtn.addEventListener("click", exportDecisions);
  el.importBtn.addEventListener("click", () => {
    el.importFile.click();
  });
  el.importFile.addEventListener("change", () => {
    importProgressFiles(el.importFile.files);
  });
  el.topBtn.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  window.addEventListener("pagehide", () => {
    if (state.unsavedLocalChanges > 0) persistDirty();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && state.unsavedLocalChanges > 0) persistDirty();
  });
}

function init() {
  if (!bundle) {
    document.body.textContent = "Mobile bundle data is missing. Rebuild the phone bundle on the Mac.";
    return;
  }
  loadSavedProgress();
  rebuildDuplicateGroups();
  const imageStatus = bundle.imageStatus || {};
  const offlineStatus = imageStatus.offlineReady
    ? "local"
    : `${imageStatus.localImageCount || 0}/${state.rows.length} images local`;
  const skippedImages = imageStatus.skippedRowCount ? ` | ${imageStatus.skippedRowCount} missing skipped` : "";
  el.summary.textContent = `${state.rows.length} cards | ${offlineStatus}${skippedImages}`;
  fillSelects();
  if (state.dirty.size > 0 || state.reviewed.size > 0) {
    el.stateFilter.value = "NEUTRAL";
  }
  renderBucketSelect();
  renderBatchSelect();
  bindEvents();
  render();
}

init();
