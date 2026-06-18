#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fwmDataDir } from "../tools/image-review-dashboard/paths.mjs";
import {
  PRODUCTION_SUPABASE_REF,
  assertProductionDatabaseUrl,
} from "./lib/dev-supabase-guard.mjs";
import { loadDotEnv } from "./lib/local-env.mjs";
import {
  postgresClientTool,
  postgresConnectionArgs,
  redactDatabaseUrl,
} from "./lib/postgres-client.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const apply = process.argv.includes("--apply");

function parseArg(name, defaultValue = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : defaultValue;
}

function safeStamp(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

function runPsqlScalar(sql) {
  const connection = postgresConnectionArgs(process.env.PROD_DATABASE_URL);
  return execFileSync(postgresClientTool("psql"), [...connection.args, "-At", "-c", sql], {
    cwd: repoRoot,
    encoding: "utf8",
    env: { ...process.env, ...connection.env },
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function pgDumpVersion() {
  return execFileSync(postgresClientTool("pg_dump"), ["--version"], {
    cwd: repoRoot,
    encoding: "utf8",
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

async function main() {
  await loadDotEnv({ cwd: repoRoot });
  assertProductionDatabaseUrl(process.env.PROD_DATABASE_URL);
  const exportedAt = new Date();
  const stamp = parseArg("stamp", safeStamp(exportedAt));
  const reportsDir = path.join(fwmDataDir(repoRoot), "_reports");
  const exportsDir = path.join(reportsDir, "baseline_exports");
  await mkdir(exportsDir, { recursive: true });

  const exportFilePath = path.join(exportsDir, `public_images_${stamp}.sql`);
  const manifestPath = path.join(reportsDir, `baseline_public_images_export_${stamp}.json`);

  console.log(`Mode: ${apply ? "apply" : "dry-run"}`);
  console.log(`Source production project ref: ${PRODUCTION_SUPABASE_REF}`);
  console.log("Source table: public.images");
  console.log(`Export SQL path: ${exportFilePath}`);
  console.log(`Manifest path: ${manifestPath}`);

  if (!apply) {
    console.log("Dry-run only. No production connection was opened and no export file was written.");
    return;
  }

  const productionRowCount = Number(runPsqlScalar("select count(*) from public.images;"));
  const connection = postgresConnectionArgs(process.env.PROD_DATABASE_URL);
  execFileSync(
    postgresClientTool("pg_dump"),
    [
      ...connection.args,
      "--data-only",
      "--table=public.images",
      "--column-inserts",
      "--no-owner",
      "--no-privileges",
      "--file",
      exportFilePath,
    ],
    {
      cwd: repoRoot,
      stdio: "inherit",
      env: { ...process.env, ...connection.env },
    },
  );

  const manifest = {
    exported_at: exportedAt.toISOString(),
    source_supabase_project_ref: PRODUCTION_SUPABASE_REF,
    source_table: "public.images",
    production_row_count: productionRowCount,
    export_file_path: exportFilePath,
    export_file_sha256: await sha256File(exportFilePath),
    export_method: "pg_dump --data-only",
    pg_dump_version: pgDumpVersion(),
    notes:
      "Production remains live; rows created after exported_at are out of scope for this dev baseline.",
  };

  await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  console.log(`Wrote baseline manifest: ${manifestPath}`);
  console.log(`Production row count: ${productionRowCount}`);
  console.log(`Export SHA-256: ${manifest.export_file_sha256}`);
}

main().catch((error) => {
  console.error(redactDatabaseUrl(error.message || error));
  process.exitCode = 1;
});
