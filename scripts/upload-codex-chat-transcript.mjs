import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
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

async function uploadTranscriptRow({ supabaseUrl, serviceRoleKey, row }) {
  const endpoint = `${supabaseUrl}/rest/v1/codex_chat_transcripts?on_conflict=chat_key`;
  const headers = {
    apikey: serviceRoleKey,
    Authorization: `Bearer ${serviceRoleKey}`,
    "Content-Type": "application/json",
    Prefer: "resolution=merge-duplicates,return=representation",
  };

  async function postRow(bodyRow) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(bodyRow),
    });

    if (response.ok) {
      return response;
    }

    const text = await response.text();
    let parsedError = null;
    try {
      parsedError = JSON.parse(text);
    } catch {
      parsedError = null;
    }

    return {
      ok: false,
      status: response.status,
      text,
      parsedError,
    };
  }

  const initial = await postRow(row);
  if (initial.ok) {
    return initial;
  }

  const missingTimingColumn =
    initial.status === 400 &&
    initial.parsedError?.code === "PGRST204" &&
    typeof initial.parsedError?.message === "string" &&
    (
      initial.parsedError.message.includes("transcript_started_at") ||
      initial.parsedError.message.includes("transcript_ended_at")
    );

  if (!missingTimingColumn) {
    throw new Error(`Supabase upload failed (${initial.status}): ${initial.text}`);
  }

  const fallbackRow = { ...row };
  delete fallbackRow.transcript_started_at;
  delete fallbackRow.transcript_ended_at;

  const fallback = await postRow(fallbackRow);
  if (!fallback.ok) {
    throw new Error(`Supabase upload failed (${fallback.status}): ${fallback.text}`);
  }

  return fallback;
}

function normalizeIsoTimestamp(value) {
  if (!value) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  if (typeof value === "number") {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = new Date(trimmed);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }
  return null;
}

function findMessageTimestamp(message) {
  if (!message || typeof message !== "object") return null;
  const directKeys = [
    "timestamp",
    "created_at",
    "createdAt",
    "time",
    "sent_at",
    "sentAt",
  ];
  for (const key of directKeys) {
    const normalized = normalizeIsoTimestamp(message[key]);
    if (normalized) return normalized;
  }

  if (message.metadata && typeof message.metadata === "object") {
    for (const key of directKeys) {
      const normalized = normalizeIsoTimestamp(message.metadata[key]);
      if (normalized) return normalized;
    }
  }

  return null;
}

async function resolveTranscriptTiming(parsed, transcriptPath) {
  const metadata = parsed?.metadata && typeof parsed.metadata === "object" ? parsed.metadata : {};
  const startedCandidates = [
    parsed?.transcript_started_at,
    parsed?.conversation_started_at,
    parsed?.started_at,
    metadata.transcript_started_at,
    metadata.conversation_started_at,
    metadata.started_at,
  ];
  const endedCandidates = [
    parsed?.transcript_ended_at,
    parsed?.conversation_ended_at,
    parsed?.ended_at,
    parsed?.generated_at,
    metadata.transcript_ended_at,
    metadata.conversation_ended_at,
    metadata.ended_at,
    metadata.generated_at,
  ];

  let transcriptStartedAt =
    startedCandidates.map(normalizeIsoTimestamp).find(Boolean) || null;
  let transcriptEndedAt =
    endedCandidates.map(normalizeIsoTimestamp).find(Boolean) || null;

  const messages = Array.isArray(parsed?.messages) ? parsed.messages : [];
  if (!transcriptStartedAt) {
    transcriptStartedAt = messages.map(findMessageTimestamp).find(Boolean) || null;
  }
  if (!transcriptEndedAt) {
    transcriptEndedAt = [...messages].reverse().map(findMessageTimestamp).find(Boolean) || null;
  }

  const fileStats = await stat(transcriptPath);
  if (!transcriptStartedAt && fileStats.birthtimeMs > 0) {
    transcriptStartedAt = new Date(fileStats.birthtimeMs).toISOString();
  }
  if (!transcriptEndedAt) {
    transcriptEndedAt = new Date(fileStats.mtimeMs).toISOString();
  }

  return {
    transcriptStartedAt,
    transcriptEndedAt,
  };
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

function buildSummaryPrompt({
  title,
  source,
  messageCount,
  localFilePath,
  transcriptStartedAt,
  transcriptEndedAt,
  fullText,
}) {
  return [
    "Summarize this Codex work transcript into durable project context.",
    "Use only facts grounded in the transcript.",
    "If something is unclear, use an empty string or empty array rather than guessing.",
    "",
    `Title: ${title}`,
    `Source: ${source}`,
    `Message count: ${messageCount}`,
    `Local transcript path: ${localFilePath}`,
    `Conversation started at: ${transcriptStartedAt || ""}`,
    `Conversation ended at: ${transcriptEndedAt || ""}`,
    "",
    "Transcript:",
    fullText,
  ].join("\n");
}

async function generateContextSummary({
  title,
  source,
  messageCount,
  localFilePath,
  transcriptStartedAt,
  transcriptEndedAt,
  fullText,
}) {
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
              text: buildSummaryPrompt({
                title,
                source,
                messageCount,
                localFilePath,
                transcriptStartedAt,
                transcriptEndedAt,
                fullText,
              }),
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

async function generateContextSummaryWithFallback(input) {
  try {
    return {
      ...(await generateContextSummary(input)),
      summaryError: null,
    };
  } catch (error) {
    return {
      model: null,
      summary: "",
      summaryJson: {
        summary: "",
        project: "",
        goals: [],
        decisions_made: [],
        open_tasks: [],
        blockers: [],
        important_paths: [],
        important_env_vars: [],
        next_steps: [],
      },
      summaryError: error instanceof Error ? error.message : String(error),
    };
  }
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
  const { transcriptStartedAt, transcriptEndedAt } = await resolveTranscriptTiming(parsed, transcriptPath);
  const { model, summary, summaryJson, summaryError } = await generateContextSummaryWithFallback({
    title,
    source,
    messageCount: messages.length,
    localFilePath: transcriptPath,
    transcriptStartedAt,
    transcriptEndedAt,
    fullText,
  });

  const transcriptWithTiming = {
    ...parsed,
    transcript_started_at: transcriptStartedAt,
    transcript_ended_at: transcriptEndedAt,
    generated_at: parsed.generated_at || now,
    metadata: {
      ...(parsed.metadata && typeof parsed.metadata === "object" ? parsed.metadata : {}),
      transcript_started_at: transcriptStartedAt,
      transcript_ended_at: transcriptEndedAt,
      uploaded_at: now,
    },
  };

  const row = {
    chat_key: chatKey,
    source,
    title,
    transcript_started_at: transcriptStartedAt,
    transcript_ended_at: transcriptEndedAt,
    transcript_json: transcriptWithTiming,
    full_text: fullText,
    context_summary: summary,
    context_summary_json: {
      ...summaryJson,
      summary_model: model,
      summary_error: summaryError,
      transcript_started_at: transcriptStartedAt,
      transcript_ended_at: transcriptEndedAt,
    },
    message_count: messages.length,
    local_file_path: transcriptPath,
    updated_at: now,
  };

  const supabaseUrl = requiredEnv("SUPABASE_URL");
  const serviceRoleKey = requiredEnv("SUPABASE_SERVICE_ROLE_KEY");
  const response = await uploadTranscriptRow({ supabaseUrl, serviceRoleKey, row });

  const result = await response.json();
  const saved = Array.isArray(result) ? result[0] : result;
  console.log(
    JSON.stringify(
      {
        ok: true,
        chat_key: saved?.chat_key ?? chatKey,
        message_count: row.message_count,
        title,
        transcript_started_at: transcriptStartedAt,
        transcript_ended_at: transcriptEndedAt,
        summary_model: model,
        summary_error: summaryError,
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
