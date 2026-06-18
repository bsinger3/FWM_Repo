import { readFile } from "node:fs/promises";
import path from "node:path";

export async function loadDotEnv({ cwd = process.cwd(), override = false } = {}) {
  const envPath = path.resolve(cwd, ".env");
  let loaded = false;
  try {
    const raw = await readFile(envPath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIndex = trimmed.indexOf("=");
      if (eqIndex === -1) continue;
      const key = trimmed.slice(0, eqIndex).trim();
      let value = trimmed.slice(eqIndex + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (key && (override || !(key in process.env) || process.env[key] === "")) {
        process.env[key] = value;
      }
    }
    loaded = true;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  return { envPath, loaded };
}

export function getRepoRootFromScript(importMetaUrl, relativeFromScript = "..") {
  return path.resolve(path.dirname(new URL(importMetaUrl).pathname), relativeFromScript);
}
