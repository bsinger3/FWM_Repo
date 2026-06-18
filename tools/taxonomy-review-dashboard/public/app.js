const IMAGE_PROXY = "https://fwm-proxy.bsinger3.workers.dev/?url=";
const decisionStorageKeyPrefix = "fwm-taxonomy-review-decisions";
const INITIAL_RENDER_LIMIT = 120;
const RENDER_INCREMENT = 120;

const state = {
  packet: null,
  decisions: new Map(),
  pinnedDecisionIds: new Set(),
  filters: {
    search: "",
    decision: "",
    category: "",
  },
  clickMode: "inspect",
  decisionStorageKey: "",
  focusedIndex: 0,
  renderLimit: INITIAL_RENDER_LIMIT,
};

const el = {
  sourceSummary: document.getElementById("source-summary"),
  saveStatus: document.getElementById("save-status"),
  saveBtn: document.getElementById("save-btn"),
  searchInput: document.getElementById("search-input"),
  decisionFilter: document.getElementById("decision-filter"),
  categoryFilter: document.getElementById("category-filter"),
  clickInspect: document.getElementById("click-inspect"),
  clickApprove: document.getElementById("click-approve"),
  clickReject: document.getElementById("click-reject"),
  clickNotProduct: document.getElementById("click-not-product"),
  visibleCount: document.getElementById("visible-count"),
  approveVisible: document.getElementById("approve-visible"),
  needsReviewVisible: document.getElementById("needs-review-visible"),
  loadMore: document.getElementById("load-more"),
  grid: document.getElementById("grid"),
};

function proxied(url) {
  if (!url) return "";
  return `${IMAGE_PROXY}${encodeURIComponent(url)}`;
}

function decisionFor(id) {
  return state.decisions.get(id) || { product_page_id: id, decision: "unreviewed", reviewer_note: "" };
}

function setDecision(id, decision, note = null) {
  const current = decisionFor(id);
  state.pinnedDecisionIds.add(id);
  state.decisions.set(id, {
    ...current,
    decision,
    reviewer_note: note ?? current.reviewer_note,
    decided_at: new Date().toISOString(),
  });
  persistDecisions();
  render();
}

function resetRenderLimit() {
  state.renderLimit = INITIAL_RENDER_LIMIT;
  state.focusedIndex = 0;
  state.pinnedDecisionIds.clear();
}

function persistDecisions() {
  if (!state.decisionStorageKey) return;
  localStorage.setItem(state.decisionStorageKey, JSON.stringify(Array.from(state.decisions.values())));
}

function loadDecisions() {
  if (!state.decisionStorageKey) {
    state.decisions = new Map();
    return;
  }
  try {
    const parsed = JSON.parse(localStorage.getItem(state.decisionStorageKey) || "[]");
    state.decisions = new Map(parsed.map((decision) => [decision.product_page_id, decision]));
  } catch {
    state.decisions = new Map();
  }
}

function decisionStorageKeyFor(packet) {
  return `${decisionStorageKeyPrefix}:${packet.promotion_report_path}`;
}

function pruneDecisionsToPacket() {
  const allowedIds = new Set((state.packet?.cards || []).map((card) => card.product_page_id));
  for (const id of state.decisions.keys()) {
    if (!allowedIds.has(id)) state.decisions.delete(id);
  }
}

function labelForTag(tag) {
  return tag.label || tag.clothing_type_id || tag.tag_id || "";
}

function allLabels(card) {
  return [
    card.category?.mother_category_id,
    ...(card.item_tags || []).map(labelForTag),
    ...(card.attribute_tags || []).map((tag) => `${tag.label || tag.tag_id}${tag.tag_type ? ` (${tag.tag_type})` : ""}`),
  ].filter(Boolean);
}

function evidenceText(card) {
  return [
    card.category?.category_evidence,
    ...(card.item_tags || []).map((tag) => tag.evidence),
    ...(card.attribute_tags || []).map((tag) => tag.evidence),
  ].filter(Boolean).join(" ");
}

function cardMatches(card) {
  const decision = decisionFor(card.product_page_id).decision;
  const pinned = state.pinnedDecisionIds.has(card.product_page_id);
  if (state.filters.decision && decision !== state.filters.decision && !pinned) return false;
  if (state.filters.category && card.category?.mother_category_id !== state.filters.category) return false;
  const query = state.filters.search.trim().toLowerCase();
  if (!query) return true;
  const haystack = [
    card.normalized_product_page_url,
    card.product_title,
    card.catalog?.fetched_title,
    ...allLabels(card),
    evidenceText(card),
  ].join(" ").toLowerCase();
  return haystack.includes(query);
}

function renderTagGroup(title, tags, className = "") {
  if (!tags.length) return "";
  return `
    <div class="tag-group">
      <h3>${title}</h3>
      <div class="tags">
        ${tags.map((tag) => `<span class="tag ${className}" title="${escapeAttr(tag.evidence || "")}">${escapeHtml(labelForTag(tag))}</span>`).join("")}
      </div>
    </div>
  `;
}

function renderImage(url, alt) {
  if (!url) return `<div class="image-missing">No image found</div>`;
  return `<img src="${escapeAttr(proxied(url))}" data-fallback-src="${escapeAttr(url)}" alt="${escapeAttr(alt)}" loading="lazy" referrerpolicy="no-referrer" />`;
}

function renderReviewImage(card) {
  if (card.review_image?.review_image_url) {
    return renderImage(card.review_image.review_image_url, "Customer review image");
  }
  return `<div class="image-missing image-warning">No customer review image found for this product page</div>`;
}

function renderCatalogImage(card) {
  if (card.catalog?.catalog_image_url) {
    return renderImage(card.catalog.catalog_image_url, "Catalog product image");
  }
  const url = card.final_url || card.normalized_product_page_url || "";
  return `<div class="image-missing catalog-lazy" data-catalog-url="${escapeAttr(url)}">Catalog image loading</div>`;
}

function hydrateCatalogPreviews() {
  const placeholders = Array.from(el.grid.querySelectorAll(".catalog-lazy[data-catalog-url]"));
  if (!placeholders.length) return;
  const load = async (placeholder) => {
    const url = placeholder.dataset.catalogUrl || "";
    if (!url || placeholder.dataset.loading) return;
    placeholder.dataset.loading = "1";
    try {
      const response = await fetch(`/api/catalog-preview?url=${encodeURIComponent(url)}`);
      const catalog = await response.json();
      if (catalog.catalog_image_url) {
        placeholder.outerHTML = renderImage(catalog.catalog_image_url, "Catalog product image");
      } else {
        placeholder.textContent = "No catalog image found";
      }
    } catch {
      placeholder.textContent = "Catalog image unavailable";
    }
  };
  if (!("IntersectionObserver" in window)) {
    placeholders.slice(0, 80).forEach(load);
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      load(entry.target);
    }
  }, { rootMargin: "700px 0px" });
  placeholders.forEach((placeholder) => observer.observe(placeholder));
}

function renderCard(card, index) {
  const decision = decisionFor(card.product_page_id);
  const categoryTag = card.category
    ? [{
        label: `${card.category.mother_category_id} (${card.category.category_confidence})`,
        evidence: card.category.category_evidence,
      }]
    : [];
  const decisionClass = decision.decision === "unreviewed" ? "" : decision.decision;
  const clickable = state.clickMode === "inspect" ? "" : "clickable";
  const focused = index === state.focusedIndex ? "focused" : "";
  return `
    <article class="card ${decisionClass} ${clickable} ${focused}" data-id="${escapeAttr(card.product_page_id)}">
      <div class="card-header">
        <a class="url" href="${escapeAttr(card.normalized_product_page_url)}" target="_blank" rel="noreferrer">${escapeHtml(card.normalized_product_page_url)}</a>
        <h2 class="title">${escapeHtml(card.product_title || "Untitled product")}</h2>
      </div>
      <div class="images">
        <div class="image-panel">
          <h3>Catalog Image</h3>
          <div class="image-frame">${renderCatalogImage(card)}</div>
        </div>
        <div class="image-panel">
          <h3>Review Image</h3>
          <div class="image-frame">${renderReviewImage(card)}</div>
        </div>
      </div>
      <div class="taxonomy">
        ${renderTagGroup("Primary Category", categoryTag, "category")}
        ${renderTagGroup("Item Tags", card.item_tags || [])}
        ${renderTagGroup("Attribute Tags", card.attribute_tags || [])}
      </div>
      <div class="actions">
        <button class="approve ${decision.decision === "approved" ? "active" : ""}" type="button" data-action="approved">Approve</button>
        <button class="reject ${decision.decision === "rejected" ? "active" : ""}" type="button" data-action="rejected">Reject</button>
        <button class="not-product ${decision.decision === "not_product" ? "active" : ""}" type="button" data-action="not_product">Not product</button>
        <button class="needs-review ${decision.decision === "needs_review" ? "active" : ""}" type="button" data-action="needs_review">Needs review</button>
        <textarea class="note" placeholder="Optional note">${escapeHtml(decision.reviewer_note || "")}</textarea>
      </div>
    </article>
  `;
}

function populateCategoryFilter() {
  const categories = Array.from(new Set((state.packet?.cards || []).map((card) => card.category?.mother_category_id).filter(Boolean))).sort();
  el.categoryFilter.innerHTML = '<option value="">All categories</option>' +
    categories.map((category) => `<option value="${escapeAttr(category)}">${escapeHtml(category)}</option>`).join("");
}

function setClickMode(mode) {
  state.clickMode = mode;
  for (const button of [el.clickInspect, el.clickApprove, el.clickReject, el.clickNotProduct]) {
    button.classList.toggle("active", button.dataset.clickMode === mode);
  }
  render();
}

function visibleCards() {
  return (state.packet?.cards || []).filter(cardMatches);
}

function renderedCards() {
  return visibleCards().slice(0, state.renderLimit);
}

function updateSummary(visible) {
  const total = state.packet?.cards?.length || 0;
  const cardIds = new Set((state.packet?.cards || []).map((card) => card.product_page_id));
  const scoped = Array.from(state.decisions.values()).filter((decision) => cardIds.has(decision.product_page_id));
  const approved = scoped.filter((decision) => decision.decision === "approved").length;
  const rejected = scoped.filter((decision) => decision.decision === "rejected").length;
  const notProduct = scoped.filter((decision) => decision.decision === "not_product").length;
  const needsReview = scoped.filter((decision) => decision.decision === "needs_review").length;
  const reviewed = approved + rejected + notProduct + needsReview;
  const unreviewed = Math.max(0, total - reviewed);
  const shown = Math.min(visible.length, state.renderLimit);
  el.visibleCount.textContent = `${shown} shown of ${visible.length}`;
  el.saveStatus.textContent = `${approved} approved, ${rejected} rejected, ${notProduct} not product, ${needsReview} needs review; ${unreviewed} left of ${total}`;
}

function render({ scrollFocused = false } = {}) {
  const visible = visibleCards();
  if (state.focusedIndex >= visible.length) state.focusedIndex = Math.max(0, visible.length - 1);
  updateSummary(visible);
  if (el.loadMore) {
    const remaining = Math.max(0, visible.length - state.renderLimit);
    el.loadMore.hidden = remaining === 0;
    el.loadMore.textContent = remaining ? `Load ${Math.min(RENDER_INCREMENT, remaining)} more (${remaining} remaining)` : "Load more";
  }
  if (!visible.length) {
    el.grid.innerHTML = '<div class="empty">No cards match the current filters.</div>';
    return;
  }
  const rendered = visible.slice(0, state.renderLimit);
  el.grid.innerHTML = rendered.map(renderCard).join("");
  hydrateCatalogPreviews();
  if (scrollFocused) {
    requestAnimationFrame(() => {
      el.grid.querySelector(".card.focused")?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/'/g, "&#39;");
}

async function saveDecisions() {
  const decisions = Array.from(state.decisions.values()).filter((decision) => decision.decision !== "unreviewed");
  const decisionContext = (state.packet?.cards || []).map((card) => ({
    product_page_id: card.product_page_id,
    promotion_report_path: card.promotion_report_path,
    taxonomy_report_path: card.taxonomy_report_path,
  }));
  el.saveBtn.disabled = true;
  const previousStatus = el.saveStatus.textContent;
  el.saveStatus.textContent = `Saving ${decisions.length} decisions...`;
  const response = await fetch("/api/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      promotion_report_path: state.packet.promotion_report_path,
      promotion_report_paths: state.packet.promotion_report_paths || [],
      taxonomy_report_path: state.packet.taxonomy_report_path,
      taxonomy_report_paths: state.packet.taxonomy_report_paths || [],
      summary: state.packet.summary || {},
      decision_context: decisionContext,
      decisions,
    }),
  });
  const body = await response.json();
  if (!response.ok) {
    el.saveStatus.textContent = previousStatus;
    throw new Error(body.error || "Could not save decisions");
  }
  el.saveStatus.textContent = `Saved ${body.approved_count} approvals to ${body.output_path}`;
  el.saveBtn.disabled = false;
}

function focusedCard() {
  return visibleCards()[state.focusedIndex] || null;
}

function setFocusedDecision(decision) {
  const card = focusedCard();
  if (!card) return;
  setDecision(card.product_page_id, decision);
}

function moveFocus(delta, { unreviewedOnly = false } = {}) {
  const visible = visibleCards();
  if (!visible.length) return;
  let next = state.focusedIndex;
  for (let steps = 0; steps < visible.length; steps += 1) {
    next = Math.min(visible.length - 1, Math.max(0, next + delta));
    if (!unreviewedOnly || decisionFor(visible[next].product_page_id).decision === "unreviewed") break;
    if (next === 0 || next === visible.length - 1) break;
  }
  state.focusedIndex = next;
  if (state.focusedIndex >= state.renderLimit) {
    state.renderLimit = Math.ceil((state.focusedIndex + 1) / RENDER_INCREMENT) * RENDER_INCREMENT;
  }
  render({ scrollFocused: true });
}

function openFocusedProductPage() {
  const card = focusedCard();
  if (card?.normalized_product_page_url) window.open(card.normalized_product_page_url, "_blank", "noreferrer");
}

function wireEvents() {
  el.searchInput.addEventListener("input", () => {
    state.filters.search = el.searchInput.value;
    resetRenderLimit();
    render();
  });
  el.decisionFilter.addEventListener("change", () => {
    state.filters.decision = el.decisionFilter.value;
    resetRenderLimit();
    render();
  });
  el.categoryFilter.addEventListener("change", () => {
    state.filters.category = el.categoryFilter.value;
    resetRenderLimit();
    render();
  });
  for (const button of [el.clickInspect, el.clickApprove, el.clickReject, el.clickNotProduct]) {
    button.addEventListener("click", () => setClickMode(button.dataset.clickMode));
  }
  el.approveVisible.addEventListener("click", () => {
    for (const card of renderedCards()) {
      if (decisionFor(card.product_page_id).decision === "unreviewed") {
        state.pinnedDecisionIds.add(card.product_page_id);
        state.decisions.set(card.product_page_id, {
          product_page_id: card.product_page_id,
          decision: "approved",
          reviewer_note: "",
          decided_at: new Date().toISOString(),
        });
      }
    }
    persistDecisions();
    render();
  });
  el.needsReviewVisible.addEventListener("click", () => {
    for (const card of renderedCards()) {
      if (decisionFor(card.product_page_id).decision === "unreviewed") {
        state.pinnedDecisionIds.add(card.product_page_id);
        state.decisions.set(card.product_page_id, {
          product_page_id: card.product_page_id,
          decision: "needs_review",
          reviewer_note: "",
          decided_at: new Date().toISOString(),
        });
      }
    }
    persistDecisions();
    render();
  });
  el.loadMore?.addEventListener("click", () => {
    state.renderLimit += RENDER_INCREMENT;
    render();
  });
  el.saveBtn.addEventListener("click", () => {
    saveDecisions().catch((error) => {
      el.saveStatus.textContent = error.message || String(error);
    }).finally(() => {
      el.saveBtn.disabled = false;
    });
  });
  el.grid.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    const card = event.target.closest(".card");
    if (card) {
      const visible = visibleCards();
      const index = visible.findIndex((item) => item.product_page_id === card.dataset.id);
      if (index !== -1) state.focusedIndex = index;
    }
    if (button) {
      setDecision(card.dataset.id, button.dataset.action);
      return;
    }
    if (event.target.closest("a, textarea, input, select")) return;
    if (card && state.clickMode !== "inspect") {
      setDecision(card.dataset.id, state.clickMode);
    } else if (card) {
      render();
    }
  });
  el.grid.addEventListener("input", (event) => {
    if (!event.target.classList.contains("note")) return;
    const card = event.target.closest(".card");
    const current = decisionFor(card.dataset.id);
    state.decisions.set(card.dataset.id, {
      ...current,
      reviewer_note: event.target.value,
      decided_at: new Date().toISOString(),
    });
    persistDecisions();
  });
  el.grid.addEventListener(
    "error",
    (event) => {
      if (!(event.target instanceof HTMLImageElement)) return;
      const fallbackSrc = event.target.dataset.fallbackSrc;
      if (!fallbackSrc || event.target.src === fallbackSrc) return;
      event.target.src = fallbackSrc;
      delete event.target.dataset.fallbackSrc;
    },
    true,
  );
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isTextInput = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveDecisions().catch((error) => {
        el.saveStatus.textContent = error.message || String(error);
      }).finally(() => {
        el.saveBtn.disabled = false;
      });
      return;
    }
    if (isTextInput) return;
    const key = event.key.toLowerCase();
    if (key === "/") {
      event.preventDefault();
      el.searchInput.focus();
      return;
    }
    if (key === "a") {
      event.preventDefault();
      setFocusedDecision("approved");
    } else if (key === "r") {
      event.preventDefault();
      setFocusedDecision("rejected");
    } else if (key === "p") {
      event.preventDefault();
      setFocusedDecision("not_product");
    } else if (key === "n") {
      event.preventDefault();
      setFocusedDecision("needs_review");
    } else if (key === "u") {
      event.preventDefault();
      setFocusedDecision("unreviewed");
    } else if (key === "j") {
      event.preventDefault();
      moveFocus(1, { unreviewedOnly: event.shiftKey });
    } else if (key === "k") {
      event.preventDefault();
      moveFocus(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      openFocusedProductPage();
    }
  });
}

async function init() {
  wireEvents();
  const response = await fetch("/api/cards");
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Could not load taxonomy cards");
  state.packet = body;
  state.decisionStorageKey = decisionStorageKeyFor(body);
  loadDecisions();
  pruneDecisionsToPacket();
  persistDecisions();
  const missingReviewImageCount = body.summary?.missing_customer_review_image_count || 0;
  const missingPrimaryCategoryCount = body.summary?.missing_primary_category_count || 0;
  const alreadyDecidedCount = body.summary?.already_decided_count || 0;
  const hiddenSuffix = [
    alreadyDecidedCount ? `${alreadyDecidedCount} already decided hidden` : "",
    missingPrimaryCategoryCount ? `${missingPrimaryCategoryCount} missing primary category hidden` : "",
    missingReviewImageCount ? `${missingReviewImageCount} missing customer review images` : "",
  ].filter(Boolean).join("; ");
  el.sourceSummary.textContent = `${body.cards.length} reviewable pending updates from ${body.promotion_report_path}${hiddenSuffix ? `; ${hiddenSuffix}` : ""}`;
  populateCategoryFilter();
  render();
}

init().catch((error) => {
  el.grid.innerHTML = `<div class="empty">${escapeHtml(error.message || String(error))}</div>`;
});
