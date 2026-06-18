#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import {
  PRODUCTION_SUPABASE_REF,
  assertApprovedDevDatabaseUrl,
  assertApprovedDevSupabase,
  callSupabaseRest,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";
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

async function sha256File(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

async function readManifest(manifestPath) {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (manifest.source_supabase_project_ref !== PRODUCTION_SUPABASE_REF) {
    throw new Error(
      `Baseline manifest source ref mismatch: ${manifest.source_supabase_project_ref}`,
    );
  }
  if (manifest.source_table !== "public.images") {
    throw new Error(`Baseline manifest source_table must be public.images, got ${manifest.source_table}`);
  }
  if (manifest.export_method !== "pg_dump --data-only") {
    throw new Error(`Baseline manifest export_method is not authoritative: ${manifest.export_method}`);
  }
  if (!existsSync(manifest.export_file_path)) {
    throw new Error(`Baseline export file is missing: ${manifest.export_file_path}`);
  }
  const actualSha = await sha256File(manifest.export_file_path);
  if (actualSha !== manifest.export_file_sha256) {
    throw new Error(`Baseline export SHA-256 mismatch. Expected ${manifest.export_file_sha256}, got ${actualSha}`);
  }
  return manifest;
}

async function getDevImageCount(guard) {
  const { response } = await callSupabaseRest({
    supabaseUrl: guard.supabaseUrl,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
    path: "images",
    method: "GET",
    searchParams: { select: "id", limit: "1" },
    prefer: "count=exact",
  });
  const range = response.headers.get("content-range") || "";
  const count = Number(range.split("/").at(-1));
  return Number.isFinite(count) ? count : null;
}

async function main() {
  const manifestArg = parseArg("manifest");
  if (!manifestArg) {
    throw new Error("Usage: node scripts/restore-dev-images-baseline.mjs --manifest=/path/to/manifest.json [--apply]");
  }
  const manifestPath = path.resolve(manifestArg);

  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Baseline restore guard" });
  const manifest = await readManifest(manifestPath);
  const devImageCount = await getDevImageCount(guard);

  console.log(`Mode: ${apply ? "apply" : "dry-run"}`);
  console.log(`Manifest: ${manifestPath}`);
  console.log(`Export file: ${manifest.export_file_path}`);
  console.log(`Exported at: ${manifest.exported_at}`);
  console.log(`Production row count in manifest: ${manifest.production_row_count}`);
  console.log(`Current dev public.images count: ${devImageCount ?? "unknown"}`);

  if (!apply) {
    console.log("Dry-run only. No baseline SQL was restored.");
    return;
  }

  requireExplicitWriteFlag();
  if (devImageCount !== 0) {
    throw new Error(
      `Refusing baseline restore because dev public.images is not empty (${devImageCount} rows).`,
    );
  }
  if (!process.env.DEV_DATABASE_URL) {
    throw new Error(
      "DEV_DATABASE_URL is required for psql restore. It must point to the approved dev database, not production.",
    );
  }
  assertApprovedDevDatabaseUrl(process.env.DEV_DATABASE_URL);
  console.log(`Restoring baseline into dev ${guard.supabaseUrl} (${guard.projectRef}).`);
  const connection = postgresConnectionArgs(process.env.DEV_DATABASE_URL);
  execFileSync(
    postgresClientTool("psql"),
    [...connection.args, "--set", "ON_ERROR_STOP=1", "-f", manifest.export_file_path],
    {
      cwd: repoRoot,
      stdio: "inherit",
      env: { ...process.env, ...connection.env },
    },
  );
}

main().catch((error) => {
  console.error(redactDatabaseUrl(error.message || error));
  process.exitCode = 1;
});
