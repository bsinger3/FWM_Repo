import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

const env = {
  ...process.env,
  PLAYWRIGHT_BROWSERS_PATH: path.join(rootDir, ".playwright-browsers"),
};

const child = spawn(
  process.execPath,
  [path.join(rootDir, "node_modules", "playwright", "cli.js"), ...process.argv.slice(2)],
  {
    cwd: rootDir,
    env,
    stdio: "inherit",
  },
);

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
