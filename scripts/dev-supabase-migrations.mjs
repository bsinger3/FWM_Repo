#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import {
  DEV_SUPABASE_REF,
  PRODUCTION_SUPABASE_REF,
  assertApprovedDevSupabase,
  printGuardSummary,
  requireExplicitWriteFlag,
} from "./lib/dev-supabase-guard.mjs";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const migrationsDir = path.join(repoRoot, "supabase", "dev-migrations");
const apply = process.argv.includes("--apply");
const only = process.argv.find((arg) => arg.startsWith("--only="))?.slice("--only=".length);

function assertMigrationName(filename) {
  if (!/^\d{8}_dev_[a-z0-9_]+\.sql$/.test(filename)) {
    throw new Error(
      `Dev migration ${filename} does not follow YYYYMMDD_dev_<short_name>.sql naming.`,
    );
  }
}

async function readLinkedProjectRef() {
  try {
    return (await readFile(path.join(repoRoot, "supabase", ".temp", "project-ref"), "utf8")).trim();
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function main() {
  const guard = await assertApprovedDevSupabase({ cwd: repoRoot, requireServiceRoleKey: true });
  printGuardSummary(guard, { prefix: "Dev migration guard" });
  const linkedProjectRef = await readLinkedProjectRef();

  const allFiles = (await readdir(migrationsDir))
    .filter((filename) => filename.endsWith(".sql"))
    .filter((filename) => !only || filename === only)
    .sort();
  const planFiles = allFiles.filter((filename) => /^\d{8}_dev_/.test(filename));
  for (const filename of planFiles) assertMigrationName(filename);

  console.log(`Dev migration directory: ${migrationsDir}`);
  console.log(`Supabase CLI linked ref: ${linkedProjectRef || "not linked"}`);
  if (linkedProjectRef === PRODUCTION_SUPABASE_REF) {
    console.log("Apply is blocked: Supabase CLI is linked to production.");
  } else if (linkedProjectRef !== DEV_SUPABASE_REF) {
    console.log("Apply is blocked: Supabase CLI is not linked to the approved dev project.");
  }
  console.log(`Mode: ${apply ? "apply" : "dry-run"}`);
  console.log(`Plan migration count: ${planFiles.length}`);
  for (const filename of planFiles) {
    const sql = await readFile(path.join(migrationsDir, filename), "utf8");
    console.log(`- ${filename} (${Buffer.byteLength(sql, "utf8")} bytes)`);
  }

  if (!apply) {
    console.log("Dry-run only. No SQL was sent to Supabase.");
    return;
  }

  requireExplicitWriteFlag();
  if (linkedProjectRef !== DEV_SUPABASE_REF) {
    throw new Error(
      `Refusing to apply dev migrations because Supabase CLI is linked to ${linkedProjectRef || "nothing"}, not ${DEV_SUPABASE_REF}.`,
    );
  }
  for (const filename of planFiles) {
    const sqlPath = path.join(migrationsDir, filename);
    console.log(`Applying ${filename} to ${guard.supabaseUrl} (${guard.projectRef})`);
    execFileSync("supabase", ["db", "query", "--linked", "--file", sqlPath], {
      cwd: repoRoot,
      stdio: "inherit",
      env: process.env,
    });
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
