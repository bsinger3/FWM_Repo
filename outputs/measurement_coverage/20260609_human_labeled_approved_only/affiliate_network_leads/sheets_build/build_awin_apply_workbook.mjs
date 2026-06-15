import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "/Users/briannasinger/Projects/FWM/FWM_Repo/outputs/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads";
const sourceCsv = path.join(root, "awin_programs_to_request_join_for_review_scraping.csv");
const outputPath = path.join(root, "awin_programs_to_apply_google_sheets.xlsx");

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];
    if (quoted) {
      if (ch === '"' && next === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (ch !== "\r") {
      cell += ch;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

function recordsFromCsv(text) {
  const rows = parseCsv(text).filter((r) => r.some((c) => c !== ""));
  const headers = rows[0];
  return rows.slice(1).map((row) => Object.fromEntries(headers.map((h, i) => [h, row[i] || ""])));
}

function titleCaseTier(tier) {
  return tier === "request_now" ? "Request Now" : tier === "request_next" ? "Request Next" : "Backup Only";
}

function addSheet(workbook, name, records) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const headers = [
    "Apply Order",
    "Priority",
    "Program",
    "Domain",
    "Review Provider",
    "Scrape Readiness",
    "Why Request",
    "Approval Rate",
    "Awin Index",
    "Feed",
    "Product Reporting",
    "URL",
    "Sample Product URLs",
  ];
  const rows = records.map((r, idx) => [
    idx + 1,
    titleCaseTier(r.join_priority),
    r.programmeName,
    r.normalized_domain,
    r.review_providers,
    r.scrape_readiness,
    r.why_request,
    r.approvalRate,
    r.awinIndex,
    r.feedEnabled,
    r.productReporting,
    r.displayUrl,
    r.sample_product_urls,
  ]);
  sheet.getRangeByIndexes(0, 0, rows.length + 1, headers.length).values = [headers, ...rows];
  const used = sheet.getRangeByIndexes(0, 0, Math.max(rows.length + 1, 2), headers.length);
  used.format.font = { name: "Aptos", size: 10, color: "#1F2937" };
  used.format.wrapText = true;
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
    fill: "#1F4E5F",
    font: { bold: true, color: "#FFFFFF" },
  };
  sheet.getRangeByIndexes(0, 0, rows.length + 1, headers.length).format.borders = {
    preset: "all",
    style: "thin",
    color: "#D9E2E7",
  };
  sheet.freezePanes.freezeRows(1);
  if (rows.length > 0) {
    const table = sheet.tables.add(`A1:M${rows.length + 1}`, true, `${name.replace(/\s+/g, "")}Table`);
    table.style = "TableStyleMedium2";
    table.showFilterButton = true;
  }
  const widths = [82, 110, 230, 190, 150, 125, 330, 95, 90, 70, 120, 260, 420];
  widths.forEach((w, i) => {
    sheet.getRangeByIndexes(0, i, rows.length + 1, 1).format.columnWidthPx = w;
  });
  sheet.getRangeByIndexes(1, 0, Math.max(rows.length, 1), headers.length).format.rowHeightPx = 48;
  return sheet;
}

const records = recordsFromCsv(await fs.readFile(sourceCsv, "utf8"));
const requestNow = records.filter((r) => r.join_priority === "request_now");
const requestNext = records.filter((r) => r.join_priority === "request_next");
const backupOnly = records.filter((r) => r.join_priority === "backup_only");
const applyQueue = [...requestNow, ...requestNext];

const workbook = Workbook.create();
addSheet(workbook, "Apply Queue", applyQueue);
addSheet(workbook, "Request Now", requestNow);
addSheet(workbook, "Request Next", requestNext);
addSheet(workbook, "Backup Only", backupOnly);

const summary = workbook.worksheets.add("Summary");
summary.showGridLines = false;
summary.getRange("A1:D1").values = [["Awin Advertiser Application Queue", "", "", ""]];
summary.mergeCells("A1:D1");
summary.getRange("A1:D1").format = {
  fill: "#1F4E5F",
  font: { bold: true, color: "#FFFFFF", size: 16 },
};
summary.getRange("A3:B7").values = [
  ["Bucket", "Count"],
  ["Request Now", requestNow.length],
  ["Request Next", requestNext.length],
  ["Apply Queue Total", applyQueue.length],
  ["Backup Only", backupOnly.length],
];
summary.getRange("A3:B7").format.borders = { preset: "all", style: "thin", color: "#D9E2E7" };
summary.getRange("A3:B3").format = { fill: "#E8F1F5", font: { bold: true, color: "#1F2937" } };
summary.getRange("A10:D13").values = [
  ["How to use", "", "", ""],
  ["Start with the Apply Queue tab and submit all Request Now programs first.", "", "", ""],
  ["Use Request Next after the first batch is submitted or if Awin limits batch approvals.", "", "", ""],
  ["Backup Only is preserved for later and should not be mass-applied first.", "", "", ""],
];
summary.mergeCells("A10:D10");
summary.mergeCells("A11:D11");
summary.mergeCells("A12:D12");
summary.mergeCells("A13:D13");
summary.getRange("A10:D10").format = { fill: "#E8F1F5", font: { bold: true, color: "#1F2937" } };
summary.getRange("A1:D13").format.font = { name: "Aptos", size: 11, color: "#1F2937" };
summary.getRange("A:A").format.columnWidthPx = 180;
summary.getRange("B:B").format.columnWidthPx = 90;
summary.getRange("C:D").format.columnWidthPx = 180;

const preview = await workbook.render({ sheetName: "Apply Queue", range: "A1:M20", scale: 1, format: "png" });
await fs.writeFile(path.join(root, "awin_programs_to_apply_google_sheets_preview.png"), new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(outputPath);
