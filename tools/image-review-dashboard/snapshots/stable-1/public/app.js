const IMAGE_PROXY = "https://fwm-proxy.bsinger3.workers.dev/?url=";
const storageKey = "fwm-image-review-unsaved-decisions";
const hideSavedStorageKey = "fwm-image-review-hide-saved";
const hideDuplicatesStorageKey = "fwm-image-review-hide-duplicates";
const openedFromFile = window.location.protocol === "file:";

if (openedFromFile) {
  window.location.replace("http://localhost:4173/");
}

const state = {
  parts: null,
  bucket: "needs_human_review",
  part: "001",
  rows: [],
  rejectionReasons: [],
  selected: new Set(),
  dirty: new Map(),
  clickMode: "inspect",
  reasonFilter: "",
  legendFilter: "",
  detailRowKey: null,
  drag: null,
  undoStack: [],
  suppressCardClickUntil: 0,
};

const el = {
  sourceSummary: document.getElementById("source-summary"),
  saveStatus: document.getElementById("save-status"),
  saveBtn: document.getElementById("save-btn"),
  undoExportBtn: document.getElementById("undo-export-btn"),
  bucketTabs: document.getElementById("bucket-tabs"),
  partSelect: document.getElementById("part-select"),
  searchInput: document.getElementById("search-input"),
  stateFilter: document.getElementById("state-filter"),
  reasonFilter: document.getElementById("reason-filter"),
  clickModeInspect: document.getElementById("click-mode-inspect"),
  clickModeApprove: document.getElementById("click-mode-approve"),
  clickModeReject: document.getElementById("click-mode-reject"),
  showReasons: document.getElementById("show-reasons"),
  hideSaved: document.getElementById("hide-saved"),
  hideDuplicates: document.getElementById("hide-duplicates"),
  boxMode: document.getElementById("box-mode"),
  visibleCount: document.getElementById("visible-count"),
  selectedCount: document.getElementById("selected-count"),
  approveSelected: document.getElementById("approve-selected"),
  rejectSelected: document.getElementById("reject-selected"),
  neutralSelected: document.getElementById("neutral-selected"),
  approveVisibleUnmarked: document.getElementById("approve-visible-unmarked"),
  rejectVisibleUnmarked: document.getElementById("reject-visible-unmarked"),
  neutralVisible: document.getElementById("neutral-visible"),
  undoAction: document.getElementById("undo-action"),
  clearSelected: document.getElementById("clear-selected"),
  legend: document.getElementById("legend"),
  loading: document.getElementById("loading"),
  grid: document.getElementById("grid"),
  gridWrap: document.getElementById("grid-wrap"),
  selectionBox: document.getElementById("selection-box"),
  dialog: document.getElementById("detail-dialog"),
  detailTitle: document.getElementById("detail-title"),
  detailSubtitle: document.getElementById("detail-subtitle"),
  detailImage: document.getElementById("detail-image"),
  detailApprove: document.getElementById("detail-approve"),
  detailReject: document.getElementById("detail-reject"),
  detailNeutral: document.getElementById("detail-neutral"),
  detailNotes: document.getElementById("detail-notes"),
  detailMeta: document.getElementById("detail-meta"),
  detailApply: document.getElementById("detail-apply"),
  topBtn: document.getElementById("top-btn"),
};

function loadDirty() {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    for (const [key, decision] of Object.entries(parsed)) {
      state.dirty.set(key, decision);
    }
  } catch (error) {
    console.warn("Could not load local review decisions", error);
  }
}

function loadPreferences() {
  el.hideSaved.checked = localStorage.getItem(hideSavedStorageKey) === "true";
  el.hideDuplicates.checked = localStorage.getItem(hideDuplicatesStorageKey) !== "false";
}

function persistPreferences() {
  localStorage.setItem(hideSavedStorageKey, String(el.hideSaved.checked));
  localStorage.setItem(hideDuplicatesStorageKey, String(el.hideDuplicates.checked));
}

function persistDirty() {
  localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(state.dirty)));
  updateSaveStatus();
}

function rowDecisionKey(row) {
  return `${row.bucket}::${row.partFile}::${row.rowKey}`;
}

function getRowDecision(row) {
  const dirty = state.dirty.get(rowDecisionKey(row));
  if (dirty) return { ...row, ...dirty, savedDecisionState: "unsaved" };
  return row;
}

function buildDecision(row, patch) {
  const current = getRowDecision(row);
  const next = {
    bucket: row.bucket,
    partFile: row.partFile,
    rowKey: row.rowKey,
    sourceFile: row.source.sourceFile,
    sourceRowNumber: row.source.sourceRowNumber,
    defaultDecision: row.defaultDecision,
    cvDecision: row.cvDecision,
    cvReasonCode: row.cvReasonCode,
    cvReasonSummary: row.cvReasonSummary,
    sorterRecommendation: row.sorterRecommendation,
    sorterReasonCodes: row.sorterReasonCodes,
    humanState: patch.humanState ?? current.humanState ?? "NEUTRAL",
    rejectionReason: patch.rejectionReason ?? current.rejectionReason ?? "",
    reviewNotes: patch.reviewNotes ?? current.reviewNotes ?? "",
  };

  if (next.humanState !== "DISAPPROVE") {
    next.rejectionReason = "";
  }

  return next;
}

function snapshotRows(rows, label) {
  const targets = expandRowsForReviewUnits(rows);
  if (targets.length === 0) return null;
  return {
    label,
    entries: targets.map((row) => {
      const key = rowDecisionKey(row);
      return {
        key,
        hadDirty: state.dirty.has(key),
        dirty: state.dirty.get(key) || null,
      };
    }),
  };
}

function pushUndo(snapshot) {
  if (!snapshot) return;
  state.undoStack.push(snapshot);
  state.undoStack = state.undoStack.slice(-20);
  updateUndoStatus();
}

function undoLastAction() {
  const snapshot = state.undoStack.pop();
  if (!snapshot) return;
  for (const entry of snapshot.entries) {
    if (entry.hadDirty) state.dirty.set(entry.key, entry.dirty);
    else state.dirty.delete(entry.key);
  }
  persistDirty();
  updateUndoStatus();
  render();
}

function updateUndoStatus() {
  el.undoAction.disabled = state.undoStack.length === 0;
  const last = state.undoStack.at(-1);
  el.undoAction.textContent = last ? `Undo ${last.label}` : "Undo last action";
}

function setRowDecision(row, patch, options = {}) {
  const rows = rowsForReviewUnit(row);
  if (options.undoLabel !== false) {
    pushUndo(snapshotRows(rows, options.undoLabel || "last action"));
  }
  for (const targetRow of rows) {
    state.dirty.set(rowDecisionKey(targetRow), buildDecision(targetRow, patch));
  }
  persistDirty();
  if (options.render !== false) render();
}

function setRowDecisions(rows, patchOrFactory, options = {}) {
  const targets = expandRowsForReviewUnits(rows);
  if (targets.length === 0) return;
  if (options.undoLabel !== false) {
    pushUndo(snapshotRows(targets, options.undoLabel || "last action"));
  }
  for (const row of targets) {
    const patch =
      typeof patchOrFactory === "function"
        ? patchOrFactory(row, getRowDecision(row))
        : patchOrFactory;
    state.dirty.set(rowDecisionKey(row), buildDecision(row, patch));
  }
  persistDirty();
  render();
}

function setClickMode(mode) {
  state.clickMode = mode;
  for (const button of [el.clickModeInspect, el.clickModeApprove, el.clickModeReject]) {
    button.classList.remove("active", "approve-mode", "reject-mode");
    if (button.dataset.clickMode === mode) {
      button.classList.add("active");
      if (mode === "approve") button.classList.add("approve-mode");
      if (mode === "reject") button.classList.add("reject-mode");
    }
  }
}

function applyClickMode(row) {
  if (state.clickMode === "approve") {
    const current = getRowDecision(row);
    setRowDecision(row, { humanState: current.humanState === "APPROVE" ? "NEUTRAL" : "APPROVE" });
    return true;
  }
  if (state.clickMode === "reject") {
    const current = getRowDecision(row);
    setRowDecision(row, {
      humanState: current.humanState === "DISAPPROVE" ? "NEUTRAL" : "DISAPPROVE",
    });
    return true;
  }
  return false;
}

function formatHeight(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "";
  return `${Math.floor(n / 12)}'${Math.round(n % 12)}"`;
}

function formatWeight(value) {
  if (!value) return "";
  const raw = String(value).trim();
  if (!raw || raw.toLowerCase() === "unknown") return "";
  const range = raw.match(/\b(\d{2,3}(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?|#)?\b/i);
  if (range) return `${range[1]}-${range[2]} lb`;
  const n = Number.parseFloat(raw.replace(/[^0-9.]+/g, ""));
  if (!Number.isFinite(n)) return raw;
  return `${Number.isInteger(n) ? n : n.toFixed(1).replace(/\.0$/, "")} lb`;
}

function shortReason(reason) {
  if (!reason) return "";
  return reason
    .replace(/^BORDERLINE_/, "BORDERLINE ")
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function reasonForRow(row) {
  const decision = getRowDecision(row);
  return decision.rejectionReason || row.cvReasonCode || row.sorterReasonCodes || row.defaultDecision || row.bucket;
}

function reasonColor(reason) {
  const value = String(reason || "").toUpperCase();
  if (value.includes("BODY") || value.includes("GARMENT") || value.includes("COVERAGE") || value.includes("CUT")) {
    return "#2563eb";
  }
  if (value.includes("MULTIPLE") || value.includes("AMBIGUOUS")) {
    return "#7c3aed";
  }
  if (value.includes("NO_PERSON") || value.includes("NOT_WORN")) {
    return "#64748b";
  }
  if (value.includes("FETCH") || value.includes("RESOLUTION") || value.includes("DARK") || value.includes("BLUR") || value.includes("BRIGHT") || value.includes("GRAIN")) {
    return "#b7791f";
  }
  if (value.includes("WRONG") || value.includes("CONTEXT")) {
    return "#c2410c";
  }
  if (value.includes("DUPLICATE")) {
    return "#0f766e";
  }
  return "#667085";
}

function imageSrc(url) {
  if (!url) return "";
  return `${IMAGE_PROXY}${encodeURIComponent(url)}`;
}

function fillReasonSelect(select, includeBlank = false) {
  select.textContent = "";
  if (includeBlank) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No reason selected";
    select.appendChild(option);
  }
  for (const reason of state.rejectionReasons) {
    const option = document.createElement("option");
    option.value = reason;
    option.textContent = shortReason(reason);
    select.appendChild(option);
  }
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

async function init() {
  loadDirty();
  loadPreferences();
  state.parts = await fetchJson("/api/parts");
  state.part = firstRemainingPart(state.parts.buckets[state.bucket])?.part || state.part;
  renderTabs();
  updateSourceSummary();
  await loadRows();
  bindEvents();
}

function updateSourceSummary() {
  const bucketCount = Object.values(state.parts.buckets)
    .map((bucket) => `${bucket.label}: ${bucket.remainingPartCount} batches left`)
    .join(" | ");
  el.sourceSummary.textContent = `${state.parts.packageId} | ${bucketCount}`;
}

function firstRemainingPart(config) {
  return config.parts.find((part) => part.remainingRowCount > 0) || config.parts[0];
}

function renderTabs() {
  el.bucketTabs.textContent = "";
  for (const bucket of ["approve_candidates", "needs_human_review", "disapprove_candidates"]) {
    const config = state.parts.buckets[bucket];
    const button = document.createElement("button");
    button.className = bucket === state.bucket ? "tab active" : "tab";
    button.type = "button";
    button.textContent = `${config.label} (${config.remainingPartCount})`;
    button.title = `${config.remainingPartCount} batches still have work; ${config.remainingRowCount} unreviewed of ${config.rowCount} rows`;
    button.addEventListener("click", async () => {
      state.bucket = bucket;
      state.part = firstRemainingPart(config)?.part || "001";
      state.selected.clear();
      renderTabs();
      await loadRows();
    });
    el.bucketTabs.appendChild(button);
  }
}

function renderPartSelect() {
  const parts = state.parts.buckets[state.bucket].parts;
  el.partSelect.textContent = "";
  for (const part of parts) {
    const option = document.createElement("option");
    option.value = part.part;
    option.textContent = `Part ${part.part} (${part.remainingRowCount} left)`;
    option.selected = part.part === state.part;
    el.partSelect.appendChild(option);
  }
}

function nextCandidatePart(visitedParts = new Set()) {
  const parts = state.parts.buckets[state.bucket].parts;
  const startIndex = Math.max(parts.findIndex((part) => part.part === state.part), 0);
  const ordered = [...parts.slice(startIndex + 1), ...parts.slice(0, startIndex)];
  return ordered.find((part) => part.remainingRowCount > 0 && !visitedParts.has(part.part));
}

async function loadRows(visitedParts = new Set()) {
  visitedParts.add(state.part);
  el.loading.hidden = false;
  el.grid.textContent = "";
  renderPartSelect();
  const data = await fetchJson(`/api/rows?bucket=${encodeURIComponent(state.bucket)}&part=${encodeURIComponent(state.part)}`);
  state.rows = data.rows;
  decorateDuplicateCounts();
  state.rejectionReasons = data.rejectionReasons;
  renderReasonFilter();
  if (el.hideSaved.checked && filteredRows().length === 0) {
    const nextPart = nextCandidatePart(visitedParts);
    if (nextPart) {
      state.part = nextPart.part;
      return loadRows(visitedParts);
    }
  }
  el.loading.hidden = true;
  render();
}

function decorateDuplicateCounts() {
  const counts = new Map();
  for (const row of state.rows) {
    const key = duplicateImageKey(row);
    if (!key) continue;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  for (const row of state.rows) {
    const key = duplicateImageKey(row);
    row.duplicateImageKey = key;
    row.duplicateImageCount = key ? counts.get(key) || 1 : 1;
  }
}

function duplicateImageKey(row) {
  const imageUrl = row.imageUrl || row.rawImageUrl || "";
  return imageUrl.trim().toLowerCase();
}

function rowsForReviewUnit(row) {
  if (!el.hideDuplicates.checked || !row.duplicateImageKey) return [row];
  return state.rows.filter((candidate) => candidate.duplicateImageKey === row.duplicateImageKey);
}

function expandRowsForReviewUnits(rows) {
  const expanded = new Map();
  for (const row of rows) {
    for (const targetRow of rowsForReviewUnit(row)) {
      expanded.set(rowDecisionKey(targetRow), targetRow);
    }
  }
  return Array.from(expanded.values());
}

function renderReasonFilter() {
  const reasons = new Set();
  for (const row of state.rows) {
    const decision = getRowDecision(row);
    if (decision.rejectionReason) reasons.add(decision.rejectionReason);
    if (row.cvReasonCode) reasons.add(row.cvReasonCode);
    if (row.sorterReasonCodes) reasons.add(row.sorterReasonCodes);
  }
  el.reasonFilter.textContent = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All reasons";
  el.reasonFilter.appendChild(all);
  for (const reason of Array.from(reasons).sort()) {
    const option = document.createElement("option");
    option.value = reason;
    option.textContent = shortReason(reason);
    el.reasonFilter.appendChild(option);
  }
}

function passesFilters(row) {
  const decision = getRowDecision(row);
  if (el.hideSaved.checked && decision.savedDecisionState === "saved") return false;

  const q = el.searchInput.value.trim().toLowerCase();
  if (q) {
    const haystack = [
      row.rowKey,
      row.source.sourceFile,
      row.display.userComment,
      row.display.productTitle,
      row.display.productCategory,
      row.display.clothingType,
      decision.reviewNotes,
    ]
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(q)) return false;
  }

  const stateFilter = el.stateFilter.value;
  if (stateFilter === "dirty" && !state.dirty.has(rowDecisionKey(row))) return false;
  if (stateFilter === "saved" && decision.savedDecisionState !== "saved") return false;
  if (["APPROVE", "DISAPPROVE", "NEUTRAL"].includes(stateFilter) && decision.humanState !== stateFilter) return false;

  const reasonFilter = state.legendFilter || el.reasonFilter.value;
  if (reasonFilter) {
    const values = [decision.rejectionReason, row.cvReasonCode, row.sorterReasonCodes, row.defaultDecision];
    if (!values.includes(reasonFilter)) return false;
  }

  return true;
}

function filteredRows() {
  const rows = state.rows.filter(passesFilters);
  if (!el.hideDuplicates.checked) return rows;

  const representatives = new Map();
  for (const row of rows) {
    if (!row.duplicateImageKey) continue;
    const current = representatives.get(row.duplicateImageKey);
    if (!current) {
      representatives.set(row.duplicateImageKey, row);
      continue;
    }
    const currentDecision = getRowDecision(current);
    const rowDecision = getRowDecision(row);
    if (currentDecision.savedDecisionState === "saved" && rowDecision.savedDecisionState !== "saved") {
      representatives.set(row.duplicateImageKey, row);
    }
  }

  const seen = new Set();
  return rows.filter((row) => {
    if (!row.duplicateImageKey) return true;
    const representative = representatives.get(row.duplicateImageKey);
    if (row !== representative || seen.has(row.duplicateImageKey)) return false;
    seen.add(row.duplicateImageKey);
    return true;
  });
}

function appendMeta(row, label, value) {
  if (!value) return "";
  return `<span class="meta-pill"><span class="meta-pill-label">${escapeHtml(label)}</span><span class="meta-pill-value">${escapeHtml(value)}</span></span>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderCard(row) {
  const decision = getRowDecision(row);
  const article = document.createElement("article");
  const selected = state.selected.has(rowDecisionKey(row));
  const stateClass = decision.humanState === "APPROVE" ? "approved" : decision.humanState === "DISAPPROVE" ? "rejected" : "";
  article.className = ["card", stateClass, selected ? "selected" : ""].filter(Boolean).join(" ");
  article.dataset.key = rowDecisionKey(row);

  const reason = reasonForRow(row);
  const bra = row.display.braBandIn && row.display.cupSize ? `${row.display.braBandIn}${row.display.cupSize}` : row.display.bustIn ? `${row.display.bustIn}" bust` : "";
  const summary = [
    appendMeta(row, "", formatHeight(row.display.heightIn)),
    appendMeta(row, "", formatWeight(row.display.weightLbs)),
    appendMeta(row, "", bra),
    appendMeta(row, "Waist", row.display.waistIn ? `${row.display.waistIn}"` : ""),
    appendMeta(row, "Hips", row.display.hipsIn ? `${row.display.hipsIn}"` : ""),
  ].join("");
  const cvSummary = [
    el.showReasons.checked ? appendMeta(row, "CV", shortReason(row.cvReasonCode || row.defaultDecision)) : "",
    row.duplicateImageCount > 1 ? appendMeta(row, "Dup", `x${row.duplicateImageCount}`) : "",
  ].join("");

  article.innerHTML = `
    ${decision.reviewNotes ? '<div class="note-chip">Note</div>' : ""}
    ${decision.savedDecisionState === "saved" ? '<div class="saved-chip">Saved</div>' : ""}
    <img alt="" loading="lazy" referrerpolicy="no-referrer" src="${escapeHtml(imageSrc(row.imageUrl))}" data-original="${escapeHtml(row.imageUrl)}" />
    <div class="meta">
      <div class="meta-row">${summary}</div>
      <div class="meta-row">${cvSummary}</div>
    </div>
    <div class="card-actions">
      <button type="button" title="Approve" class="approve-action ${decision.humanState === "APPROVE" ? "active" : ""}">A</button>
      <button type="button" title="Reject" class="reject-action ${decision.humanState === "DISAPPROVE" ? "active" : ""}">R</button>
      <button type="button" title="Neutral" class="neutral-action">N</button>
      <button type="button" title="Details" class="detail-action">i</button>
    </div>
  `;

  const img = article.querySelector("img");
  img.addEventListener("error", () => {
    if (img.src !== row.imageUrl && row.imageUrl) {
      img.src = row.imageUrl;
    } else {
      img.style.display = "none";
    }
  });

  article.addEventListener("click", (event) => {
    if (Date.now() < state.suppressCardClickUntil) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const button = event.target.closest("button");
    if (button?.classList.contains("approve-action")) {
      const current = getRowDecision(row);
      setRowDecision(row, { humanState: current.humanState === "APPROVE" ? "NEUTRAL" : "APPROVE" });
      return;
    }
    if (button?.classList.contains("reject-action")) {
      const current = getRowDecision(row);
      setRowDecision(row, {
        humanState: current.humanState === "DISAPPROVE" ? "NEUTRAL" : "DISAPPROVE",
      });
      return;
    }
    if (button?.classList.contains("neutral-action")) {
      setRowDecision(row, { humanState: "NEUTRAL" });
      return;
    }
    if (button?.classList.contains("detail-action")) {
      openDetail(row);
      return;
    }
    if (el.boxMode.checked) {
      toggleSelected(row);
      return;
    }
    if (applyClickMode(row)) {
      return;
    }
    openDetail(row);
  });

  return article;
}

function render() {
  const rows = filteredRows();
  el.grid.textContent = "";
  const fragment = document.createDocumentFragment();
  for (const row of rows) fragment.appendChild(renderCard(row));
  el.grid.appendChild(fragment);
  renderLegend(rows);
  updateCounts(rows);
  updateSaveStatus();
}

function renderLegend(rows) {
  const counts = new Map();
  for (const row of rows) {
    const reason = reasonForRow(row);
    counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  el.legend.textContent = "";
  for (const [reason, count] of Array.from(counts.entries()).sort((a, b) => b[1] - a[1])) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = reason === state.legendFilter ? "legend-item active" : "legend-item";
    item.innerHTML = `<span class="swatch" style="--reason-color:${reasonColor(reason)}"></span><span>${escapeHtml(shortReason(reason))}</span><strong>${count}</strong>`;
    item.addEventListener("click", () => {
      state.legendFilter = state.legendFilter === reason ? "" : reason;
      render();
    });
    el.legend.appendChild(item);
  }
}

function updateCounts(rows = filteredRows()) {
  el.visibleCount.textContent = `${rows.length} visible`;
  el.selectedCount.textContent = `${state.selected.size} selected`;
}

function updateSaveStatus() {
  const dirtyCount = state.dirty.size;
  el.saveStatus.textContent = dirtyCount ? `${dirtyCount} unsaved decision${dirtyCount === 1 ? "" : "s"}` : "No unsaved changes";
  el.saveBtn.disabled = dirtyCount === 0;
  updateUndoStatus();
}

function toggleSelected(row) {
  toggleSelectedKey(rowDecisionKey(row));
}

function toggleSelectedKey(key) {
  if (state.selected.has(key)) {
    state.selected.delete(key);
  } else {
    state.selected.add(key);
  }
  render();
}

function selectedRows() {
  const keys = state.selected;
  return state.rows.filter((row) => keys.has(rowDecisionKey(row)));
}

function applyToSelected(patch) {
  setRowDecisions(selectedRows(), patch, { undoLabel: "selected action" });
}

function visibleUnmarkedRows() {
  return expandRowsForReviewUnits(filteredRows()).filter((row) => getRowDecision(row).humanState === "NEUTRAL");
}

function applyToVisibleUnmarked(patch) {
  setRowDecisions(visibleUnmarkedRows(), patch, { undoLabel: "visible bulk action" });
}

function applyToVisibleRows(patch) {
  setRowDecisions(filteredRows(), patch, { undoLabel: "visible action" });
}

function openDetail(row) {
  const decision = getRowDecision(row);
  state.detailRowKey = rowDecisionKey(row);
  el.detailTitle.textContent = row.display.productTitle || row.display.clothingType || "Review image";
  el.detailSubtitle.textContent = `${shortReason(row.cvReasonCode || row.defaultDecision)} | ${row.rowKey}`;
  el.detailImage.src = imageSrc(row.imageUrl);
  el.detailImage.onerror = () => {
    if (el.detailImage.src !== row.imageUrl) el.detailImage.src = row.imageUrl;
  };
  el.detailNotes.value = decision.reviewNotes || "";
  renderDetailMeta(row, decision);
  el.dialog.showModal();
}

function renderDetailMeta(row, decision) {
  const fields = [
    ["Human state", decision.humanState],
    ["Rejection reason", shortReason(decision.rejectionReason)],
    ["Review notes", decision.reviewNotes],
    ["Size", row.display.size],
    ["Height", formatHeight(row.display.heightIn)],
    ["Weight", formatWeight(row.display.weightLbs)],
    ["Bra/bust", row.display.braBandIn && row.display.cupSize ? `${row.display.braBandIn}${row.display.cupSize}` : row.display.bustIn],
    ["Waist", row.display.waistIn],
    ["Hips", row.display.hipsIn],
    ["CV reason", shortReason(row.cvReasonCode)],
    ["CV summary", row.cvReasonSummary],
    ["Sorter reasons", row.sorterReasonCodes],
    ["Duplicate image count", row.duplicateImageCount > 1 ? row.duplicateImageCount : ""],
    ["User comment", row.display.userComment],
    ["Product URL", row.productUrl],
    ["Source file", row.source.sourceFile],
    ["Source row", row.source.sourceRowNumber],
  ];
  el.detailMeta.innerHTML = fields
    .filter(([, value]) => value)
    .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
}

function getDetailRow() {
  return state.rows.find((row) => rowDecisionKey(row) === state.detailRowKey);
}

function saveDetailPatch(patch) {
  const row = getDetailRow();
  if (!row) return;
  setRowDecision(row, {
    ...patch,
    reviewNotes: el.detailNotes.value,
  });
  openDetail(row);
}

async function saveProgress() {
  const decisions = Array.from(state.dirty.values());
  el.saveBtn.disabled = true;
  el.saveStatus.textContent = "Saving...";
  const result = await fetchJson("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  state.dirty.clear();
  persistDirty();
  state.parts = await fetchJson("/api/parts");
  updateSourceSummary();
  alert(`Saved ${decisions.length} decision(s).\nGenerated ${result.outputs.length} workbook(s).`);
  await loadRows();
}

async function undoLastExport() {
  state.parts = await fetchJson("/api/parts");
  updateSourceSummary();
  const latestExport = state.parts.latestExport;
  if (!latestExport) {
    alert("There is no export to undo.");
    return;
  }

  const proceed = confirm(
    [
      "Undo the most recent export?",
      "",
      `Export: ${latestExport.exportStamp}`,
      `Generated workbooks: ${latestExport.workbookCount}`,
      `Affected decisions: ${latestExport.decisionCount}`,
      "",
      "This will delete only the generated files for that export and put those decisions back into editable unsaved state.",
    ].join("\n"),
  );
  if (!proceed) return;

  el.undoExportBtn.disabled = true;
  el.saveStatus.textContent = "Undoing last export...";
  const result = await fetchJson("/api/undo-last-export", { method: "POST" });

  if (!result.undone) {
    alert(result.message || "There is no export to undo.");
    el.undoExportBtn.disabled = false;
    updateSaveStatus();
    return;
  }

  for (const decision of result.decisions || []) {
    const key = `${decision.bucket}::${decision.partFile}::${decision.rowKey}`;
    state.dirty.set(key, decision);
  }
  persistDirty();
  state.parts = await fetchJson("/api/parts");
  updateSourceSummary();
  await loadRows();
  alert(
    `Undid export ${result.exportStamp}.\nDeleted ${result.deletedFiles.length} generated file(s).\nRestored ${result.decisions.length} decision(s) as unsaved edits.`,
  );
  el.undoExportBtn.disabled = false;
}

function bindEvents() {
  el.partSelect.addEventListener("change", async () => {
    state.part = el.partSelect.value;
    state.selected.clear();
    await loadRows();
  });
  for (const input of [el.searchInput, el.stateFilter, el.reasonFilter, el.showReasons, el.hideSaved, el.hideDuplicates]) {
    input.addEventListener("input", () => {
      if (input === el.reasonFilter) state.legendFilter = "";
      if (input === el.hideSaved || input === el.hideDuplicates) persistPreferences();
      render();
    });
  }
  el.boxMode.addEventListener("input", () => {
    if (el.boxMode.checked) setClickMode("inspect");
  });
  el.approveSelected.addEventListener("click", () => applyToSelected({ humanState: "APPROVE" }));
  el.rejectSelected.addEventListener("click", () => {
    applyToSelected({ humanState: "DISAPPROVE" });
  });
  el.neutralSelected.addEventListener("click", () => applyToSelected({ humanState: "NEUTRAL" }));
  el.approveVisibleUnmarked.addEventListener("click", () => {
    applyToVisibleUnmarked({ humanState: "APPROVE" });
  });
  el.rejectVisibleUnmarked.addEventListener("click", () => {
    applyToVisibleUnmarked({ humanState: "DISAPPROVE" });
  });
  el.neutralVisible.addEventListener("click", () => {
    applyToVisibleRows({ humanState: "NEUTRAL" });
  });
  el.undoAction.addEventListener("click", () => {
    undoLastAction();
  });
  el.clearSelected.addEventListener("click", (event) => {
    event.preventDefault();
    state.selected.clear();
    el.selectedCount.textContent = "0 selected";
    render();
  });
  for (const button of [el.clickModeInspect, el.clickModeApprove, el.clickModeReject]) {
    button.addEventListener("click", () => {
      setClickMode(button.dataset.clickMode);
    });
  }
  el.saveBtn.addEventListener("click", () => saveProgress().catch((error) => {
    alert(error.message);
    updateSaveStatus();
  }));
  el.undoExportBtn.addEventListener("click", () => undoLastExport().catch((error) => {
    alert(error.message);
    el.undoExportBtn.disabled = false;
    updateSaveStatus();
  }));
  el.detailApprove.addEventListener("click", () => saveDetailPatch({ humanState: "APPROVE" }));
  el.detailReject.addEventListener("click", () => saveDetailPatch({ humanState: "DISAPPROVE" }));
  el.detailNeutral.addEventListener("click", () => saveDetailPatch({ humanState: "NEUTRAL" }));
  el.detailApply.addEventListener("click", () => saveDetailPatch({}));
  el.topBtn.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  window.addEventListener("keydown", (event) => {
    if (el.dialog.open) return;
    const rows = selectedRows();
    if (event.key.toLowerCase() === "a") applyToSelected({ humanState: "APPROVE" });
    if (event.key.toLowerCase() === "d") applyToSelected({ humanState: "DISAPPROVE" });
    if (event.key.toLowerCase() === "n") applyToSelected({ humanState: "NEUTRAL" });
    if (event.key.toLowerCase() === "c" && rows[0]) openDetail(rows[0]);
  });
  bindBoxSelect();
}

function bindBoxSelect() {
  el.grid.addEventListener("click", (event) => {
    if (!el.boxMode.checked) return;
    if (Date.now() < state.suppressCardClickUntil) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (event.target.closest("button, input, select, textarea, a")) return;

    const card = event.target.closest(".card");
    if (!card?.dataset.key) return;

    event.preventDefault();
    event.stopPropagation();
    toggleSelectedKey(card.dataset.key);
  }, true);

  el.gridWrap.addEventListener("pointerdown", (event) => {
    if (!el.boxMode.checked) return;
    if (event.target.closest("button, input, select, textarea, a")) return;
    event.preventDefault();
    state.drag = {
      startX: event.clientX,
      startY: event.clientY,
      x: event.clientX,
      y: event.clientY,
      moved: false,
    };
    el.gridWrap.setPointerCapture?.(event.pointerId);
    el.selectionBox.hidden = false;
    updateSelectionBox();
  });
  window.addEventListener("pointermove", (event) => {
    if (!state.drag) return;
    state.drag.x = event.clientX;
    state.drag.y = event.clientY;
    state.drag.moved =
      Math.abs(state.drag.x - state.drag.startX) > 4 ||
      Math.abs(state.drag.y - state.drag.startY) > 4;
    updateSelectionBox();
  });
  window.addEventListener("pointerup", (event) => {
    if (!state.drag) return;
    const moved = state.drag.moved;
    const box = el.selectionBox.getBoundingClientRect();
    state.suppressCardClickUntil = Date.now() + 250;
    if (moved) {
      for (const card of el.grid.querySelectorAll(".card")) {
        const rect = card.getBoundingClientRect();
        const overlaps =
          rect.left < box.right &&
          rect.right > box.left &&
          rect.top < box.bottom &&
          rect.bottom > box.top;
        if (overlaps) state.selected.add(card.dataset.key);
      }
    } else {
      const card = document.elementFromPoint(state.drag.x, state.drag.y)?.closest?.(".card");
      if (card?.dataset.key) toggleSelectedKey(card.dataset.key);
    }
    event.preventDefault();
    event.stopPropagation();
    state.drag = null;
    el.selectionBox.hidden = true;
    render();
  });
}

function updateSelectionBox() {
  const { startX, startY, x, y } = state.drag;
  const left = Math.min(startX, x);
  const top = Math.min(startY, y);
  const width = Math.abs(startX - x);
  const height = Math.abs(startY - y);
  Object.assign(el.selectionBox.style, {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    height: `${height}px`,
  });
}

if (!openedFromFile) {
  init().catch((error) => {
    el.loading.textContent = error.message;
    console.error(error);
  });
}
