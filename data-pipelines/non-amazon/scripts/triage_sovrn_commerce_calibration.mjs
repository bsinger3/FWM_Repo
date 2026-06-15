#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(__filename), "../../..");
const target = path.join(
  repoRoot,
  "data-pipelines/scripts/02_qualify_for_supabase/sovrn/triage_sovrn_commerce_calibration.mjs",
);

const result = spawnSync(process.execPath, [target, ...process.argv.slice(2)], {
  stdio: "inherit",
});

process.exit(result.status ?? 1);
