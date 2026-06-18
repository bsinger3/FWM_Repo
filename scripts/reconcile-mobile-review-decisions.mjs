#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fwmDataDir, defaultImageReviewReturnsDir } from "../tools/image-review-dashboard/paths.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");
const limit = Number(process.argv.find((arg) => arg.startsWith("--limit="))?.split("=")[1] || 0);

function decisionKey(decision) {
  return `${decision.bucket}::${decision.partFile || decision.part_file}::${decision.rowKey || decision.review_row_key}`;
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function main() {
  const returnsDir = process.env.FWM_IMAGE_REVIEW_RETURNS_DIR || defaultImageReviewReturnsDir(repoRoot);
  const manifestPath = path.join(returnsDir, "human_labeled_returns_manifest.json");
  const manifest = existsSync(manifestPath) ? await readJson(manifestPath) : { decisions: {} };
  const manifestKeys = new Set(Object.keys(manifest.decisions || {}));
  const manifestStat = existsSync(manifestPath) ? await stat(manifestPath) : null;
  const files = (await readdir(returnsDir))
    .filter((filename) => /^fwm_mobile_review.*\.json$/.test(filename))
    .sort();

  const unmergedFiles = [];
  let unmergedDecisionCount = 0;
  let mobileDecisionCount = 0;
  for (const filename of files) {
    const filePath = path.join(returnsDir, filename);
    const payload = await readJson(filePath);
    const decisions = Array.isArray(payload.decisions) ? payload.decisions : [];
    mobileDecisionCount += decisions.length;
    const unmerged = decisions.filter((decision) => !manifestKeys.has(decisionKey(decision)));
    if (unmerged.length) {
      unmergedFiles.push({ filename, decision_count: decisions.length, unmerged_decision_count: unmerged.length });
      unmergedDecisionCount += unmerged.length;
    }
  }

  const values = Object.values(manifest.decisions || {});
  const report = {
    generated_at: new Date().toISOString(),
    mode: apply ? "apply-requested" : "dry-run",
    manifest_path: manifestPath,
    manifest_modified_at: manifestStat?.mtime?.toISOString() || null,
    total_manifest_decisions: values.length,
    manifest_approvals: values.filter((d) => d.production_decision === "APPROVE" || d.human_state === "APPROVE").length,
    manifest_disapprovals: values.filter((d) => d.production_decision === "DISAPPROVE" || d.human_state === "DISAPPROVE").length,
    crop_adjusted_approvals: values.filter((d) => (d.production_decision === "APPROVE" || d.human_state === "APPROVE") && d.crop_has_adjustment).length,
    mobile_decision_files_scanned: files.length,
    mobile_decisions_scanned: mobileDecisionCount,
    unmerged_file_count: unmergedFiles.length,
    unmerged_decision_count: unmergedDecisionCount,
    unmerged_files: unmergedFiles,
    duplicate_review_row_key_count: values.length - new Set(values.map((d) => d.review_row_key).filter(Boolean)).size,
    missing_source_workbook_reference_count: values.filter((d) => !d.bucket || !d.part_file || !d.review_row_key).length,
  };

  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });
  const reportPath = path.join(reportsDir, `mobile_review_reconciliation_state_${report.generated_at.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");

  console.log(`Wrote reconciliation report: ${reportPath}`);
  console.log(`Manifest decisions: ${report.total_manifest_decisions}`);
  console.log(`Manifest approvals: ${report.manifest_approvals}`);
  console.log(`Mobile files scanned: ${report.mobile_decision_files_scanned}`);
  console.log(`Unmerged files: ${report.unmerged_file_count}`);
  console.log(`Unmerged decisions: ${report.unmerged_decision_count}`);
  if (report.unmerged_files.length) {
    console.log("Unmerged mobile files:");
    for (const file of report.unmerged_files) {
      console.log(`- ${file.filename}: ${file.unmerged_decision_count}/${file.decision_count}`);
    }
  }
  if (apply) {
    if (process.env.FWM_IMPORT_MOBILE_DECISIONS_OK !== "yes") {
      throw new Error("Apply mode imports local mobile decision files and requires FWM_IMPORT_MOBILE_DECISIONS_OK=yes.");
    }
    const filesToImport = report.unmerged_files.slice(0, limit > 0 ? limit : undefined);
    console.log(`Importing ${filesToImport.length} unmerged mobile decision file(s).`);
    for (const file of filesToImport) {
      const filePath = path.join(returnsDir, file.filename);
      console.log(`Importing ${filePath}`);
      execFileSync("npm", ["run", "image-review:import-mobile", "--", filePath], {
        cwd: repoRoot,
        stdio: "inherit",
        env: process.env,
      });
    }
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
