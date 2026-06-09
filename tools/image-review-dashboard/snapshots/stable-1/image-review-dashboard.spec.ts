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

async function installDashboardMocks(page: Page, savePayloads: SavePayload[] = []) {
  await page.addInitScript(() => window.localStorage.clear());
  await page.route("**/api/parts", async (route) => {
    await route.fulfill({ json: partsResponse() });
  });
  await page.route("**/api/rows?**", async (route) => {
    await route.fulfill({
      json: {
        rows,
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
  await page.route("https://fwm-proxy.bsinger3.workers.dev/**", async (route) => {
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

  await page.locator("#box-mode").check();
  await page.locator(".card").first().click();

  await expect(page.locator("#selected-count")).toHaveText("1 selected");
  await expect(page.locator("#detail-dialog")).not.toHaveAttribute("open", "");

  await page.locator("#clear-selected").click();
  await expect(page.locator("#selected-count")).toHaveText("0 selected");
  await expect(page.locator(".card.selected")).toHaveCount(0);
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
    }),
  ]);
});
