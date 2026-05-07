import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

function addReplacement(replacements, value, label) {
  if (!value || value.length < 6) return;
  replacements.push([value, `[REDACTED_${label}]`]);
}

async function loadEnvReplacements() {
  const replacements = [];
  try {
    const env = await readFile(path.resolve(process.cwd(), ".env"), "utf8");
    for (const line of env.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
      const key = trimmed.slice(0, trimmed.indexOf("=")).trim();
      const value = trimmed
        .slice(trimmed.indexOf("=") + 1)
        .trim()
        .replace(/^['"]|['"]$/g, "");
      if (/KEY|TOKEN|SECRET|PASSWORD|SUPABASE|S3_BUCKET|AWS_PROFILE|DATA_DIR|OPENAI/i.test(key)) {
        addReplacement(replacements, value, key.replace(/[^A-Z0-9_]/gi, "_").toUpperCase());
      }
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  return replacements;
}

function redactText(raw, replacements) {
  let text = raw;
  for (const [value, label] of replacements.sort((a, b) => b[0].length - a[0].length)) {
    text = text.split(value).join(label);
  }

  const patterns = [
    [/sk-proj-[A-Za-z0-9_-]{20,}/g, "[REDACTED_OPENAI_API_KEY]"],
    [/sk-[A-Za-z0-9_-]{20,}/g, "[REDACTED_OPENAI_API_KEY]"],
    [/AKIA[0-9A-Z]{16}/g, "[REDACTED_AWS_ACCESS_KEY_ID]"],
    [/(aws_secret_access_key\s*[=:]\s*)[^\s"'`\\]+/gi, "$1[REDACTED_AWS_SECRET_ACCESS_KEY]"],
    [/(SUPABASE_SERVICE_ROLE_KEY\s*[=:]\s*)[^\s"'`\\]+/gi, "$1[REDACTED_SUPABASE_SERVICE_ROLE_KEY]"],
    [/(OPENAI_API_KEY\s*[=:]\s*)[^\s"'`\\]+/gi, "$1[REDACTED_OPENAI_API_KEY]"],
    [/eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/g, "[REDACTED_JWT]"],
    [/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[REDACTED_EMAIL]"],
    [/s3:\/\/fwm-scraping-data-briannasinger/g, "s3://[REDACTED_FWM_S3_BUCKET]"],
    [/fwm-scraping-data-briannasinger/g, "[REDACTED_FWM_S3_BUCKET]"],
    [/https:\/\/gosqgqpftqlawvnyelkt\.supabase\.co/g, "https://[REDACTED_SUPABASE_PROJECT].supabase.co"],
    [/https:\/\/kmomndloorvrjzmiexxl\.supabase\.co/g, "https://[REDACTED_SUPABASE_PROJECT].supabase.co"],
    [/gosqgqpftqlawvnyelkt/g, "[REDACTED_SUPABASE_PROJECT_REF]"],
    [/kmomndloorvrjzmiexxl/g, "[REDACTED_SUPABASE_PROJECT_REF]"],
    [/gosqgqpftqlawvnyelkt/g, "[REDACTED_SUPABASE_DEV_PROJECT_ID]"],
    [/kmomndloorvrjzmiexxl/g, "[REDACTED_SUPABASE_PROD_PROJECT_ID]"],
    [/C:\\Users\\bsing\\OneDrive\\Documents\\Projects/g, "C:\\Users\\[REDACTED_USER]\\OneDrive\\Documents\\Projects"],
    [/C:\/Users\/bsing\/OneDrive\/Documents\/Projects/g, "C:/Users/[REDACTED_USER]/OneDrive/Documents/Projects"],
    [/\/Users\/briannasinger\/Projects/g, "/Users/[REDACTED_USER]/Projects"],
    [/bsinger3\/FWM_Repo/g, "[REDACTED_GITHUB_USER]/FWM_Repo"],
    [/github\.com\/bsinger3\/FWM_Repo/g, "github.com/[REDACTED_GITHUB_USER]/FWM_Repo"],
  ];
  for (const [regex, replacement] of patterns) {
    text = text.replace(regex, replacement);
  }
  return text;
}

async function main() {
  const inputArg = process.argv[2];
  if (!inputArg) {
    throw new Error("Usage: node scripts/redact-codex-transcript.mjs <input.json> [output.json]");
  }
  const outputArg = process.argv[3] || inputArg.replace(/\.json$/i, ".redacted.json");
  const inputPath = path.resolve(process.cwd(), inputArg);
  const outputPath = path.resolve(process.cwd(), outputArg);

  const raw = await readFile(inputPath, "utf8");
  const redactedRaw = redactText(raw, await loadEnvReplacements());
  const parsed = JSON.parse(redactedRaw);
  parsed.title = `${parsed.title || path.basename(inputArg)} (redacted)`;
  parsed.redaction = {
    redacted_at: new Date().toISOString(),
    source_file: inputArg,
    notes: [
      "Exact .env sensitive values replaced when present.",
      "Common API key/JWT/AWS key patterns replaced.",
      "Local usernames, private bucket name, Supabase project URLs, and GitHub username redacted.",
    ],
  };
  await writeFile(outputPath, `${JSON.stringify(parsed, null, 2)}\n`, "utf8");
  console.log(outputPath);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
