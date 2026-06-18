#!/usr/bin/env node

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import { PRODUCTION_SUPABASE_REF } from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function requireArg(name) {
  const value = parseArg(name);
  if (!value) throw new Error(`Missing --${name}=...`);
  return value;
}

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

async function main() {
  const exportFilePath = path.resolve(requireArg("export-file"));
  const productionRowCount = Number(requireArg("production-row-count"));
  if (!Number.isInteger(productionRowCount) || productionRowCount < 0) {
    throw new Error("--production-row-count must be a non-negative integer.");
  }
  if (!existsSync(exportFilePath)) {
    throw new Error(`Export file does not exist: ${exportFilePath}`);
  }

  const exportedAt = parseArg("exported-at", new Date().toISOString());
  const pgDumpVersion = parseArg("pg-dump-version", "");
  const notes =
    parseArg("notes") ||
    "Production remains live; rows created after exported_at are out of scope for this dev baseline.";
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  await mkdir(reportsDir, { recursive: true });

  const safeStamp = exportedAt.replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const manifestPath = path.join(reportsDir, `baseline_public_images_export_${safeStamp}.json`);
  const manifest = {
    exported_at: exportedAt,
    source_supabase_project_ref: PRODUCTION_SUPABASE_REF,
    source_table: "public.images",
    production_row_count: productionRowCount,
    export_file_path: exportFilePath,
    export_file_sha256: await sha256File(exportFilePath),
    export_method: "pg_dump --data-only",
    pg_dump_version: pgDumpVersion,
    notes,
  };

  await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  console.log(`Wrote baseline manifest: ${manifestPath}`);
  console.log(`Source project ref: ${manifest.source_supabase_project_ref}`);
  console.log(`Source table: ${manifest.source_table}`);
  console.log(`Production row count: ${manifest.production_row_count}`);
  console.log(`Export file SHA-256: ${manifest.export_file_sha256}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
