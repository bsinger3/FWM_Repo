import { expect, test, type Page } from "@playwright/test";

const placeholderSvg = [
  "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"240\" height=\"320\">",
  "<rect width=\"100%\" height=\"100%\" fill=\"#e5e7eb\"/>",
  "<text x=\"50%\" y=\"50%\" dominant-baseline=\"middle\" text-anchor=\"middle\"",
  " font-family=\"Arial\" font-size=\"22\" fill=\"#334155\">Review</text>",
  "</svg>",
].join("");

type SavePayload = {
  decisions: Array<Record<string, unknown>>;
};

const rows = [
  makeReviewRow("row-a", 1, "https://images.example.com/row-a.jpg"),
  makeReviewRow("row-b", 2, "https://images.example.com/row-b.jpg", {
    cvReasonCode: "LOW_RESOLUTION_AFTER_URL_REPAIR",
    cvReasonSummary: "Image may be low resolution",
  }),
];

function makeReviewRow(
  rowKey: string,
  sourceRowNumber: number,
  imageUrl: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    bucket: "needs_human_review",
    part: "001",
    partFile: "images_needing_human_review_part_001.xlsx",
    rowKey,
    imageUrl,
    rawImageUrl: imageUrl,
    productUrl: `https://shop.example.com/${rowKey}`,
    defaultDecision: "NEEDS_HUMAN_REVIEW",
    cvDecision: "NEEDS_HUMAN_REVIEW",
    cvReasonCode: "BORDERLINE_BODY_COVERAGE",
    cvReasonSummary: "Body visibility is borderline",
    sorterRecommendation: "",
    sorterReasonCodes: "BORDERLINE_BODY_COVERAGE",
    humanState: "NEUTRAL",
    rejectionReason: "",
    reviewNotes: "",
    savedDecisionState: "unsaved",
    source: {
      sourceFile: "images_needing_human_review_part_001.xlsx",
      sourceRowNumber,
    },
    display: {
      productTitle: `Jeans ${rowKey}`,
      productCategory: "jeans",
      clothingType: "jeans",
      userComment: "Sample comment",
      size: "medium",
      heightIn: 64,
      weightLbs: "128",
      braBandIn: "",
      cupSize: "",
      bustIn: "",
      waistIn: "28",
      hipsIn: "38",
    },
    ...overrides,
  };
}

function partsResponse() {
  return {
    packageId: "partial_170000_rows_cv_gated",
    latestExport: null,
    buckets: {
      approve_candidates: makeBucket("Approve Candidates", "images_to_approve_part_001.xlsx"),
      needs_human_review: makeBucket("Needs Human Review", "images_needing_human_review_part_001.xlsx"),
      disapprove_candidates: makeBucket("Disapprove Candidates", "images_to_disapprove_part_001.xlsx"),
    },
  };
}

function makeBucket(label: string, filename: string) {
  return {
    label,
    rowCount: 2,
    savedRowCount: 0,
    remainingRowCount: 2,
    remainingPartCount: 1,
    parts: [
      {
        part: "001",
        partNumber: 1,
        filename,
        rowCount: 2,
        savedRowCount: 0,
        remainingRowCount: 2,
      },
    ],
  };
}

async function installDashboardMocks(
  page: Page,
  savePayloads: SavePayload[] = [],
  options: { failFirstProxyImage?: boolean; rows?: Array<ReturnType<typeof makeReviewRow>> } = {},
) {
  await page.addInitScript(() => window.localStorage.clear());
  await page.route("**/api/parts", async (route) => {
    await route.fulfill({ json: partsResponse() });
  });
  await page.route("**/api/rows?**", async (route) => {
    await route.fulfill({
      json: {
        rows: options.rows ?? rows,
        rejectionReasons: [],
      },
    });
  });
  await page.route("**/api/save", async (route) => {
    savePayloads.push(route.request().postDataJSON() as SavePayload);
    await route.fulfill({
      json: {
        ok: true,
        outputs: ["human_labeled_returns/mock.xlsx"],
      },
    });
  });
  await page.route("**/api/undo-last-export", async (route) => {
    await route.fulfill({
      json: {
        undone: false,
        message: "There is no export to undo.",
      },
    });
  });
  let proxyImageAttempts = 0;
  await page.route("https://fwm-proxy.bsinger3.workers.dev/**", async (route) => {
    proxyImageAttempts += 1;
    if (options.failFirstProxyImage && proxyImageAttempts === 1) {
      await route.fulfill({ status: 503, body: "temporary image failure" });
      return;
    }
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

async function openDashboard(page: Page) {
  await page.goto("/tools/image-review-dashboard/public/index.html");
  await expect(page.locator(".card")).toHaveCount(2);
}

test("box-select card clicks select cards instead of opening the detail panel", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  const firstImage = page.locator(".card").first().locator("img");
  await expect(firstImage).toHaveCSS("object-fit", "cover");
  await expect(page.locator(".card").first().locator(".card-image-frame")).toHaveCSS("aspect-ratio", "3 / 4");
  await expect(page.locator(".card").first().locator(".card-title")).toHaveText("Jeans row-a");

  await page.locator("#box-mode").check();
  await page.locator(".card").first().click();

  await expect(page.locator("#selected-count")).toHaveText("1 selected");
  await expect(page.locator("#detail-dialog")).not.toHaveAttribute("open", "");

  await page.locator("#clear-selected").click();
  await expect(page.locator("#selected-count")).toHaveText("0 selected");
  await expect(page.locator(".card.selected")).toHaveCount(0);
});

test("card image retries direct URL after a temporary proxy failure", async ({ page }) => {
  await installDashboardMocks(page, [], { failFirstProxyImage: true });
  await openDashboard(page);

  const firstImage = page.locator(".card").first().locator("img");
  await expect(firstImage).toHaveJSProperty("complete", true);
  await expect(firstImage).not.toHaveJSProperty("naturalWidth", 0);
  await expect(page.locator(".card").first()).not.toHaveClass(/image-load-failed/);
});

test("unflagged crop metadata does not move card thumbnails out of frame", async ({ page }) => {
  await installDashboardMocks(page);
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "fwm-image-review-unsaved-decisions",
      JSON.stringify({
        "needs_human_review::images_needing_human_review_part_001.xlsx::row-a": {
          cropAdjustment: {
            hasCropAdjustment: false,
            cropObjectPositionXPct: 0,
            cropObjectPositionYPct: 100,
            cropZoom: 1.6,
            cropRotationDeg: 90,
          },
        },
      }),
    );
  });
  await openDashboard(page);

  const firstImage = page.locator(".card").first().locator("img");
  await expect(firstImage).toHaveCSS("object-position", "50% 50%");
  await expect(page.locator(".card").first().locator(".card-pan")).toHaveJSProperty("style.transform", "translate(0%, 0%)");
  await expect(firstImage).toHaveJSProperty("style.transform", "rotate(0deg)");
  await expect(page.locator(".card").first().locator(".crop-chip")).toHaveCount(0);
});

test("box-select drag selects every card inside the drag rectangle", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator("#box-mode").check();
  const firstBox = await page.locator(".card").first().boundingBox();
  const secondBox = await page.locator(".card").nth(1).boundingBox();
  expect(firstBox).not.toBeNull();
  expect(secondBox).not.toBeNull();

  await page.mouse.move(firstBox!.x + 8, firstBox!.y + 8);
  await page.mouse.down();
  await page.mouse.move(secondBox!.x + secondBox!.width - 8, secondBox!.y + secondBox!.height - 8, {
    steps: 8,
  });
  await page.mouse.up();

  await expect(page.locator("#selected-count")).toHaveText("2 selected");
  await expect(page.locator("#detail-dialog")).not.toHaveAttribute("open", "");
});

test("selected bulk actions reject, neutralize, and undo the selected card", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator("#box-mode").check();
  await page.locator(".card").first().click();
  await page.locator("#reject-selected").click();

  await expect(page.locator(".card.rejected")).toHaveCount(1);
  await expect(page.locator("#save-status")).toHaveText("1 unsaved decision");
  await expect(page.locator("#undo-action")).toContainText("Undo selected action");

  await page.locator("#undo-action").click();
  await expect(page.locator(".card.rejected")).toHaveCount(0);
  await expect(page.locator("#save-status")).toHaveText("No unsaved changes");

  await page.locator("#approve-selected").click();
  await expect(page.locator(".card.approved")).toHaveCount(1);

  await page.locator("#neutral-selected").click();
  await expect(page.locator(".card.approved")).toHaveCount(0);
  await expect(page.locator("#save-status")).toHaveText("1 unsaved decision");
});

test("visible bulk actions can be undone after an accidental bulk decision", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator("#reject-visible-unmarked").click();
  await expect(page.locator(".card.rejected")).toHaveCount(2);
  await expect(page.locator("#save-status")).toHaveText("2 unsaved decisions");

  await page.locator("#undo-action").click();
  await expect(page.locator(".card.rejected")).toHaveCount(0);
  await expect(page.locator("#save-status")).toHaveText("No unsaved changes");

  await page.locator("#approve-visible-unmarked").click();
  await expect(page.locator(".card.approved")).toHaveCount(2);

  await page.locator("#neutral-visible").click();
  await expect(page.locator(".card.approved")).toHaveCount(0);
});

test("bucket and part remaining counts include local completed decisions", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await expect(page.getByRole("button", { name: "Needs Human Review (1)" })).toBeVisible();
  await expect(page.locator("#part-select")).toContainText("Part 001 (2 left)");

  await page.locator("#approve-visible-unmarked").click();

  await expect(page.getByRole("button", { name: "Needs Human Review (0)" })).toBeVisible();
  await expect(page.locator("#part-select")).toContainText("Part 001 (0 left)");
  await expect(page.locator("#source-summary")).toContainText("Needs Human Review: 0 batches left");

  await page.locator("#undo-action").click();

  await expect(page.getByRole("button", { name: "Needs Human Review (1)" })).toBeVisible();
  await expect(page.locator("#part-select")).toContainText("Part 001 (2 left)");
  await expect(page.locator("#source-summary")).toContainText("Needs Human Review: 1 batches left");
});

test("hide saved also hides local completed decisions before export", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator("#hide-saved").check();
  await expect(page.locator(".card")).toHaveCount(2);

  await page.locator(".card").first().locator(".approve-action").click();

  await expect(page.locator("#visible-count")).toHaveText("1 visible");
  await expect(page.locator(".card")).toHaveCount(1);
  await expect(page.locator("#save-status")).toHaveText("1 unsaved decision");
});

test("approve candidate cards omit clear-pass CV reason text", async ({ page }) => {
  await installDashboardMocks(page, [], {
    rows: rows.map((row) => ({
      ...row,
      bucket: "approve_candidates",
      defaultDecision: "APPROVE",
      cvDecision: "APPROVE",
      cvReasonCode: "CLEAR_PASS",
      cvReasonSummary: "Clear Pass",
    })),
  });
  await openDashboard(page);

  await page.getByRole("button", { name: "Approve Candidates (1)", exact: true }).click();

  await expect(page.locator(".card").first().locator(".card-title")).toHaveText("Jeans row-a");
  await expect(page.locator(".card").first().locator(".meta")).not.toContainText("CV Clear Pass");
});

test("rotation-only crop adjustment keeps the full card image visible", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator(".card").first().locator(".detail-action").click();
  await page.locator("#crop-rotate").click();
  await expect(page.locator("#crop-zoom")).toHaveValue("1");
  await expect(page.locator("#crop-pan")).toHaveJSProperty("style.transform", "translate(0%, 0%)");
  const cropPanRatio = await page.locator("#crop-pan").evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.width / rect.height;
  });
  expect(cropPanRatio).toBeCloseTo(3 / 4, 1);
  const cropImageRatio = await page.locator("#crop-image").evaluate((img) => {
    const style = getComputedStyle(img);
    return parseFloat(style.width) / parseFloat(style.height);
  });
  expect(cropImageRatio).toBeCloseTo(4 / 3, 1);
  await expect(page.locator("#crop-image")).toHaveJSProperty("style.transform", "rotate(90deg)");
  await page.locator("#detail-apply").click();

  const firstImage = page.locator(".card").first().locator("img");
  await expect(firstImage).toHaveCSS("object-fit", "cover");
  await expect(page.locator(".card").first().locator(".card-pan")).toHaveJSProperty("style.transform", "translate(0%, 0%)");
  const cardImageRatio = await firstImage.evaluate((img) => {
    const style = getComputedStyle(img);
    return parseFloat(style.width) / parseFloat(style.height);
  });
  expect(cardImageRatio).toBeCloseTo(4 / 3, 1);
  await expect(firstImage).toHaveJSProperty("style.transform", "rotate(90deg)");
  await expect(page.locator(".card").first().locator(".crop-chip")).toHaveText("Crop");
});

test("crop pan sliders stay on screen axes after rotation", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator(".card").first().locator(".detail-action").click();
  await page.locator("#crop-rotate").click();
  await page.locator("#crop-y").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "80";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });

  await expect(page.locator("#crop-zoom")).toHaveValue("1.18");
  await expect(page.locator("#crop-pan")).toHaveJSProperty("style.transform", "translate(-7.63%, -12.2%)");
  await expect(page.locator("#crop-image")).toHaveCSS("object-fit", "cover");
  await expect(page.locator("#crop-image")).toHaveJSProperty("style.transform", "rotate(90deg)");
  await expect(page.locator("#crop-image")).toHaveCSS("object-position", "50% 80%");
});

test("crop sliders can reach every edge of the zoomed cover image", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator(".card").first().locator(".detail-action").click();
  await page.locator("#crop-y").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "0";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("#crop-image")).toHaveCSS("object-position", "50% 0%");
  await expect(page.locator("#crop-pan")).toHaveJSProperty("style.transform", "translate(-7.63%, 0%)");

  await page.locator("#crop-y").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "100";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("#crop-image")).toHaveCSS("object-position", "50% 100%");
  await expect(page.locator("#crop-pan")).toHaveJSProperty("style.transform", "translate(-7.63%, -15.25%)");

  await page.locator("#crop-x").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "0";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("#crop-image")).toHaveCSS("object-position", "0% 100%");
  await expect(page.locator("#crop-pan")).toHaveJSProperty("style.transform", "translate(0%, -15.25%)");

  await page.locator("#crop-x").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "100";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("#crop-image")).toHaveCSS("object-position", "100% 100%");
  await expect(page.locator("#crop-pan")).toHaveJSProperty("style.transform", "translate(-15.25%, -15.25%)");

  await page.locator("#detail-apply").click();

  const firstCard = page.locator(".card").first();
  await expect(firstCard.locator(".crop-chip")).toHaveText("Crop");
  await expect(firstCard.locator("img")).toHaveCSS("object-fit", "cover");
  await expect(firstCard.locator("img")).toHaveCSS("object-position", "100% 100%");
  await expect(firstCard.locator(".card-pan")).toHaveJSProperty("style.transform", "translate(-15.25%, -15.25%)");
});

test("clicking the crop frame does not auto-zoom", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  await page.locator(".card").first().locator(".detail-action").click();
  await page.locator("#crop-frame").click();

  await expect(page.locator("#crop-zoom")).toHaveValue("1");
  await expect(page.locator("#crop-status")).toHaveText("No manual crop saved");
  await expect(page.locator("#crop-pan")).toHaveJSProperty("style.transform", "translate(0%, 0%)");
});

test("detail dialog scroll returns all the way to the top", async ({ page }) => {
  await installDashboardMocks(page);
  await openDashboard(page);

  const dialog = page.locator("#detail-dialog");
  await page.locator(".card").first().locator(".detail-action").click();
  await expect(dialog).toHaveAttribute("open", "");
  await dialog.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect
    .poll(() => dialog.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);
  await dialog.evaluate((element) => {
    element.scrollTop = 0;
  });
  await expect
    .poll(() => dialog.evaluate((element) => element.scrollTop))
    .toBe(0);
});

test("card action buttons, detail actions, and export preserve CV review metadata", async ({ page }) => {
  const savePayloads: SavePayload[] = [];
  await installDashboardMocks(page, savePayloads);
  await openDashboard(page);

  await page.locator(".card").first().locator(".approve-action").click();
  await expect(page.locator(".card.approved")).toHaveCount(1);

  await page.locator(".card").first().locator(".approve-action").click();
  await expect(page.locator(".card.approved")).toHaveCount(0);

  await page.locator(".card").first().locator(".detail-action").click();
  await expect(page.locator("#detail-dialog")).toHaveAttribute("open", "");
  await page.locator("#detail-notes").fill("Approve after inspection");
  await page.locator("#crop-x").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "72";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.locator("#crop-y").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "28";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("#crop-zoom")).toHaveValue("1.18");
  await page.locator("#crop-zoom").evaluate((input) => {
    const range = input as HTMLInputElement;
    range.value = "1.24";
    range.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.locator("#crop-rotate").click();
  await expect(page.locator("#crop-status")).toContainText("Manual crop");
  await expect(page.locator("#crop-status")).toContainText("90deg rotation");
  await expect(page.locator("#crop-image")).toHaveCSS("object-fit", "cover");
  await page.locator("#detail-apply").click();
  await expect(page.locator("#detail-dialog")).not.toHaveAttribute("open", "");
  await expect(page.locator(".card").first().locator("img")).toHaveCSS("object-position", "72% 28%");
  await expect(page.locator(".card").first().locator("img")).toHaveCSS("object-fit", "cover");
  await expect(page.locator(".card").first().locator(".card-pan")).toHaveJSProperty(
    "style.transform",
    "translate(-13.94%, -5.42%)",
  );
  await expect(page.locator(".card").first().locator("img")).toHaveJSProperty(
    "style.transform",
    "rotate(90deg)",
  );
  await expect(page.locator("#crop-frame")).toHaveCSS("aspect-ratio", "3 / 4");
  await expect(page.locator(".card").first().locator(".meta")).toBeVisible();
  await expect(page.locator(".card").first().locator(".crop-chip")).toHaveText("Crop");

  await page.locator(".card").first().locator(".detail-action").click();
  await page.locator("#detail-approve").click();
  await page.keyboard.press("Escape");

  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("Saved 1 decision");
    await dialog.accept();
  });
  await page.locator("#save-btn").click();

  expect(savePayloads).toHaveLength(1);
  expect(savePayloads[0].decisions).toEqual([
    expect.objectContaining({
      humanState: "APPROVE",
      reviewNotes: "Approve after inspection",
      cvReasonCode: "BORDERLINE_BODY_COVERAGE",
      cvReasonSummary: "Body visibility is borderline",
      sorterReasonCodes: "BORDERLINE_BODY_COVERAGE",
      cropAdjustment: expect.objectContaining({
        hasCropAdjustment: true,
        cropMode: "object-position",
        cropAspectRatio: "3:4",
        cropObjectPositionXPct: 72,
        cropObjectPositionYPct: 28,
        cropZoom: 1.24,
        cropRotationDeg: 90,
      }),
    }),
  ]);
});
