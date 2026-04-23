import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const DEFAULT_OPENAI_MODEL = "gpt-5.2";

async function loadDotEnv() {
  const envPath = path.resolve(process.cwd(), ".env");
  try {
    const raw = await readFile(envPath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIndex = trimmed.indexOf("=");
      if (eqIndex === -1) continue;
      const key = trimmed.slice(0, eqIndex).trim();
      const value = trimmed.slice(eqIndex + 1).trim();
      if (key && !(key in process.env)) {
        process.env[key] = value;
      }
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function flattenValue(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.map(flattenValue).filter(Boolean).join("\n");
  }
  if (typeof value === "object") {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    if (Array.isArray(value.content)) {
      return value.content.map(flattenValue).filter(Boolean).join("\n");
    }
    return JSON.stringify(value);
  }
  return String(value);
}

function flattenMessages(messages) {
  return messages
    .map((message) => {
      const role = String(message.role || "unknown").toUpperCase();
      const text = flattenValue(message.text ?? message.content ?? message);
      return `${role}:\n${text}`;
    })
    .join("\n\n---\n\n");
}

function buildChatKey({ source, title, fullText }) {
  const hash = createHash("sha256").update(fullText).digest("hex").slice(0, 16);
  const titleSlug = String(title || "untitled-chat")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return `${source}-${titleSlug}-${hash}`;
}

function buildSummaryPrompt({ title, source, messageCount, localFilePath, fullText }) {
  return [
    "Summarize this Codex work transcript into durable project context.",
    "Use only facts grounded in the transcript.",
    "If something is unclear, use an empty string or empty array rather than guessing.",
    "",
    `Title: ${title}`,
    `Source: ${source}`,
    `Message count: ${messageCount}`,
    `Local transcript path: ${localFilePath}`,
    "",
    "Transcript:",
    fullText,
  ].join("\n");
}

async function generateContextSummary({ title, source, messageCount, localFilePath, fullText }) {
  const apiKey = requiredEnv("OPENAI_API_KEY");
  const model = process.env.OPENAI_MODEL || DEFAULT_OPENAI_MODEL;

  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      input: [
        {
          role: "system",
          content: [
            {
              type: "input_text",
              text:
                "You extract structured project memory from Codex chat transcripts. Return JSON matching the schema exactly. Keep summaries concise, factual, and useful for resuming work later.",
            },
          ],
        },
        {
          role: "user",
          content: [
            {
              type: "input_text",
              text: buildSummaryPrompt({ title, source, messageCount, localFilePath, fullText }),
            },
          ],
        },
      ],
      text: {
        format: {
          type: "json_schema",
          name: "codex_chat_context_summary",
          strict: true,
          schema: {
            type: "object",
            additionalProperties: false,
            properties: {
              summary: { type: "string" },
              project: { type: "string" },
              goals: {
                type: "array",
                items: { type: "string" },
              },
              decisions_made: {
                type: "array",
                items: { type: "string" },
              },
              open_tasks: {
                type: "array",
                items: { type: "string" },
              },
              blockers: {
                type: "array",
                items: { type: "string" },
              },
              important_paths: {
                type: "array",
                items: { type: "string" },
              },
              important_env_vars: {
                type: "array",
                items: { type: "string" },
              },
              next_steps: {
                type: "array",
                items: { type: "string" },
              },
            },
            required: [
              "summary",
              "project",
              "goals",
              "decisions_made",
              "open_tasks",
              "blockers",
              "important_paths",
              "important_env_vars",
              "next_steps",
            ],
          },
        },
      },
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`OpenAI summary generation failed (${response.status}): ${text}`);
  }

  const result = await response.json();
  const outputText =
    result.output_text ||
    result.output?.flatMap((item) => item.content || []).find((item) => item.type === "output_text")?.text;

  if (!outputText) {
    throw new Error("OpenAI summary generation failed: empty output_text");
  }

  const parsed = JSON.parse(outputText);
  return {
    model,
    summary: parsed.summary,
    summaryJson: parsed,
  };
}

async function main() {
  await loadDotEnv();

  const transcriptPathArg = process.argv[2] || "codex-chat-transcript.json";
  const transcriptPath = path.resolve(process.cwd(), transcriptPathArg);
  const source = process.argv[3] || "codex";

  const raw = await readFile(transcriptPath, "utf8");
  const parsed = JSON.parse(raw);
  const messages = Array.isArray(parsed.messages) ? parsed.messages : [];
  const fullText = flattenMessages(messages);
  const title = parsed.title || path.basename(transcriptPath);
  const now = new Date().toISOString();
  const chatKey = buildChatKey({ source, title, fullText });
  const { model, summary, summaryJson } = await generateContextSummary({
    title,
    source,
    messageCount: messages.length,
    localFilePath: transcriptPath,
    fullText,
  });

  const row = {
    chat_key: chatKey,
    source,
    title,
    transcript_json: parsed,
    full_text: fullText,
    context_summary: summary,
    context_summary_json: {
      ...summaryJson,
      summary_model: model,
    },
    message_count: messages.length,
    local_file_path: transcriptPath,
    updated_at: now,
  };

  const supabaseUrl = requiredEnv("SUPABASE_URL");
  const serviceRoleKey = requiredEnv("SUPABASE_SERVICE_ROLE_KEY");
  const response = await fetch(
    `${supabaseUrl}/rest/v1/codex_chat_transcripts?on_conflict=chat_key`,
    {
      method: "POST",
      headers: {
        apikey: serviceRoleKey,
        Authorization: `Bearer ${serviceRoleKey}`,
        "Content-Type": "application/json",
        Prefer: "resolution=merge-duplicates,return=representation",
      },
      body: JSON.stringify(row),
    },
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Supabase upload failed (${response.status}): ${text}`);
  }

  const result = await response.json();
  const saved = Array.isArray(result) ? result[0] : result;
  console.log(
    JSON.stringify(
      {
        ok: true,
        chat_key: saved?.chat_key ?? chatKey,
        message_count: row.message_count,
        title,
        summary_model: model,
        context_summary: summary,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
