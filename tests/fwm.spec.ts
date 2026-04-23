import { expect, test, type Page } from "@playwright/test";

type TableRow = Record<string, unknown>;

type SupabaseCall =
  | { type: "select"; table: string; filters: Array<{ method: string; args: unknown[] }> }
  | { type: "insert"; table: string; payload: TableRow | TableRow[] }
  | { type: "rpc"; fn: string; args: Record<string, unknown> | null };

const placeholderSvg = [
  "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"60\" height=\"80\">",
  "<rect width=\"100%\" height=\"100%\" fill=\"#ececec\"/>",
  "<text x=\"50%\" y=\"50%\" dominant-baseline=\"middle\" text-anchor=\"middle\"",
  " font-family=\"Arial\" font-size=\"10\" fill=\"#666\">FWM</text>",
  "</svg>",
].join("");

function makeImage(id: string, overrides: TableRow = {}): TableRow {
  return {
    id,
    original_url_display: `https://images.example.com/${id}.jpg`,
    product_page_url_display: `https://shop.example.com/products/${id}`,
    monetized_product_url_display: `https://affiliate.example.com/${id}`,
    brand: "Sample Brand",
    source_site_display: "Example Shop",
    height_in_display: 65,
    weight_display_display: "140 lb",
    size_display: "M",
    color_display: "Navy",
    bust_in_number_display: 34,
    cupsize_display: "DD",
    waist_in: 29,
    hips_in_display: 40,
    inseam_inches_display: 30,
    age_years_display: 31,
    ...overrides,
  };
}

const randomRows = [makeImage("random-1"), makeImage("random-2", { size_display: "L" })];
const searchRows = [
  makeImage("search-1", {
    height_in_display: 65,
    weight_display_display: "140 lb",
    bust_in_number_display: 34,
    cupsize_display: "DD",
    waist_in: 29,
    hips_in_display: 40,
  }),
];

async function installAppMocks(page: Page) {
  await page.route("https://www.googletagmanager.com/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/javascript; charset=utf-8",
      body: "",
    });
  });

  await page.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/javascript; charset=utf-8",
      body: supabaseStubModule,
    });
  });

  await page.route("https://fwm-proxy.bsinger3.workers.dev/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: placeholderSvg,
    });
  });

  await page.route("https://images.example.com/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: placeholderSvg,
    });
  });
}

async function readSupabaseCalls(page: Page): Promise<SupabaseCall[]> {
  return page.evaluate(() => {
    return JSON.parse(JSON.stringify((window as typeof window & { __fwmCalls?: unknown[] }).__fwmCalls || []));
  });
}

test.beforeEach(async ({ page }) => {
  await installAppMocks(page);
});

test("homepage renders random results and loads browser-visible cards", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#out .card")).toHaveCount(2);
  await expect(page.locator("#result-count-container")).toBeEmpty();
  await expect(page.locator("#out .card").first()).toContainText("Size");
  await expect(page.locator("#out .card img").first()).toBeVisible();
  await expect(page.locator("#clothing-type option")).toContainText(["All Types", "Dresses", "Jeans"]);

  const calls = await readSupabaseCalls(page);
  expect(calls).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ type: "select", table: "clothing_types" }),
      expect.objectContaining({ type: "select", table: "images" }),
    ]),
  );
});

test("search renders results and records the expected Supabase inserts and RPC calls", async ({ page }) => {
  await page.goto("/");

  await page.locator("#h-ft").fill("5");
  await page.locator("#h-in").fill("5");
  await page.locator("#w").fill("140");
  await page.locator("#b").fill("34");
  await page.locator("#cup-size").fill("dd");
  await page.locator("#waist").fill("29");
  await page.locator("#p").fill("40");
  await page.locator("#require-height").check();
  await page.locator("#clothing-type").selectOption("dress");
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page.locator("#main")).toHaveClass(/expanded/);
  await expect(page.locator("#result-count-container")).toContainText("Found 1 result");
  await expect(page.locator("#out .card")).toHaveCount(1);
  await expect(page.locator("#out .card").first()).toContainText("34DD");

  const calls = await readSupabaseCalls(page);
  const searchInsert = calls.find(
    (call): call is Extract<SupabaseCall, { type: "insert" }> =>
      call.type === "insert" && call.table === "search_events",
  );
  const matchRpc = calls.find(
    (call): call is Extract<SupabaseCall, { type: "rpc" }> =>
      call.type === "rpc" && call.fn === "match_by_measurements",
  );
  const updateRpc = calls.find(
    (call): call is Extract<SupabaseCall, { type: "rpc" }> =>
      call.type === "rpc" && call.fn === "update_search_event_metrics",
  );

  expect(searchInsert).toBeTruthy();
  expect(searchInsert?.payload).toEqual(
    expect.objectContaining({
      feet: 5,
      inches: 5,
      weight_lb: 140,
      bust_in: 34,
      hips_in: 40,
      clothing_type: "dress",
    }),
  );
  expect(matchRpc?.args).toEqual(
    expect.objectContaining({
      in_height: 65,
      in_weight: 140,
      in_bust: 34,
      in_cup_size: "DD",
      in_waist: 29,
      in_hips: 40,
      in_clothing_type_id: "dress",
      require_height: true,
      limit_n: 24,
      offset_n: 0,
    }),
  );
  expect(updateRpc?.args).toEqual(
    expect.objectContaining({
      p_results_count: 1,
    }),
  );
});

test("report an image shows the report UI and inserts into image_reports", async ({ page }) => {
  await page.goto("/");

  const firstCard = page.locator("#out .card").first();
  await expect(firstCard).toBeVisible();
  await firstCard.locator(".report-btn").click();
  await expect(firstCard.locator(".report-dropdown")).toHaveClass(/open/);

  await firstCard.getByRole("button", { name: "Duplicate image" }).click();

  await expect(firstCard.locator(".report-thanks")).toContainText("Thanks for the report!");
  await expect(page.locator("#out .card")).toHaveCount(1);

  const calls = await readSupabaseCalls(page);
  const reportInsert = calls.find(
    (call): call is Extract<SupabaseCall, { type: "insert" }> =>
      call.type === "insert" && call.table === "image_reports",
  );

  expect(reportInsert?.payload).toEqual(
    expect.objectContaining({
      image_id: "random-1",
      reason: "duplicate_image",
    }),
  );
});

const supabaseStubModule = `
const randomRows = ${JSON.stringify(randomRows)};
const searchRows = ${JSON.stringify(searchRows)};
const clothingTypes = [
  { id: "dress", label: "Dresses", sort_order: 1 },
  { id: "jeans", label: "Jeans", sort_order: 2 }
];
const cupSizes = [{ cup_size: "D" }, { cup_size: "DD" }, { cup_size: "DDD" }];

function ensureState() {
  if (!window.__fwmCalls) window.__fwmCalls = [];
  if (!window.__fwmState) {
    window.__fwmState = {
      searchEventId: null,
      lastSearchResultsCount: null
    };
  }
  return window.__fwmState;
}

class QueryBuilder {
  constructor(table) {
    this.table = table;
    this.filters = [];
    this.selectedColumns = null;
    this.insertPayload = null;
  }

  select(columns) {
    this.selectedColumns = columns;
    return this;
  }

  order(...args) {
    this.filters.push({ method: "order", args });
    return this;
  }

  not(...args) {
    this.filters.push({ method: "not", args });
    return this;
  }

  neq(...args) {
    this.filters.push({ method: "neq", args });
    return this;
  }

  or(...args) {
    this.filters.push({ method: "or", args });
    return this;
  }

  limit(...args) {
    this.filters.push({ method: "limit", args });
    return this;
  }

  ilike(...args) {
    this.filters.push({ method: "ilike", args });
    return this;
  }

  insert(payload) {
    const state = ensureState();
    window.__fwmCalls.push({ type: "insert", table: this.table, payload });
    if (this.table === "search_events" && payload && !Array.isArray(payload)) {
      state.searchEventId = payload.id;
    }
    return Promise.resolve({ data: Array.isArray(payload) ? payload : [payload], error: null });
  }

  then(resolve, reject) {
    const response = this.#buildResponse();
    return Promise.resolve(response).then(resolve, reject);
  }

  #buildResponse() {
    window.__fwmCalls.push({ type: "select", table: this.table, filters: this.filters });
    if (this.table === "clothing_types") {
      return { data: clothingTypes, error: null };
    }
    if (this.table === "images") {
      return { data: randomRows, error: null };
    }
    return { data: [], error: null };
  }
}

export function createClient() {
  ensureState();
  return {
    from(table) {
      return new QueryBuilder(table);
    },
    rpc(fn, args) {
      const state = ensureState();
      window.__fwmCalls.push({ type: "rpc", fn, args: args || null });
      if (fn === "get_distinct_cup_sizes") {
        return Promise.resolve({ data: cupSizes, error: null });
      }
      if (fn === "match_by_measurements") {
        state.lastSearchResultsCount = searchRows.length;
        return Promise.resolve({ data: searchRows, error: null });
      }
      if (fn === "update_search_event_metrics") {
        return Promise.resolve({ data: null, error: null });
      }
      return Promise.resolve({ data: null, error: null });
    }
  };
}
`
