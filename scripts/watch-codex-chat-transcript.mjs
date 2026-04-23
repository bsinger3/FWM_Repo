import { spawn } from "node:child_process";
import { existsSync, watch } from "node:fs";
import path from "node:path";

const transcriptPathArg = process.argv[2] || "codex-chat-transcript.json";
const source = process.argv[3] || "codex";
const transcriptPath = path.resolve(process.cwd(), transcriptPathArg);

if (!existsSync(transcriptPath)) {
  console.error(`Transcript file not found: ${transcriptPath}`);
  process.exit(1);
}

let timer = null;
let running = false;
let queued = false;

function runUpload() {
  if (running) {
    queued = true;
    return;
  }

  running = true;
  const child = spawn(
    process.execPath,
    ["scripts/upload-codex-chat-transcript.mjs", transcriptPath, source],
    {
      cwd: process.cwd(),
      stdio: "inherit",
    },
  );

  child.on("exit", () => {
    running = false;
    if (queued) {
      queued = false;
      runUpload();
    }
  });
}

function scheduleUpload() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    console.log(`[watch:codex-chat] syncing ${transcriptPath}`);
    runUpload();
  }, 750);
}

console.log(`[watch:codex-chat] watching ${transcriptPath}`);
console.log("[watch:codex-chat] press Ctrl+C to stop");

watch(transcriptPath, {}, () => {
  scheduleUpload();
});
