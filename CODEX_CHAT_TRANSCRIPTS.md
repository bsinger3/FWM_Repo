# Codex Chat Transcript Archiving

This repo can archive full Codex chat transcripts into Supabase and generate a structured context summary for each chat.

## What This Adds

- A private dev-only Supabase table: `codex_chat_transcripts`
- A local upload script:

```bash
node scripts/upload-codex-chat-transcript.mjs codex-chat-transcript.json
```

- A convenience npm script:

```bash
npm run sync:codex-chat
```

- An optional watcher for near-automatic syncing:

```bash
npm run watch:codex-chat
```

## Required Environment Variables

Add these to `.env` on the machine that will upload transcripts:

```text
SUPABASE_URL=https://gosqgqpftqlawvnyelkt.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
OPENAI_API_KEY=...
# Optional:
# OPENAI_MODEL=gpt-5.2
```

Use the service role key, not the anon key. The table is intentionally locked down so only the service role can insert, update, or read transcript rows.

## How Upload Works

The upload script:

1. Reads `codex-chat-transcript.json`
2. Builds a `full_text` version from all messages
3. Uses the OpenAI Responses API to generate a structured context summary
4. Computes a deterministic `chat_key`
5. Upserts the transcript into `codex_chat_transcripts`

It also handles slightly richer transcript message shapes than plain `{ role, text }`, so a future export with nested `content` still gets flattened into `full_text`.

If you rerun the script for the same transcript, it updates the existing row instead of creating duplicates.

## Important Limitation

This repo can store and upload transcripts, but it cannot by itself detect the exact moment a Codex desktop chat ends.

So there are two separate steps:

1. Generate or update the local transcript JSON file.
2. Run the upload script.

That means truly automatic end-of-chat syncing needs an external trigger, such as:

- a Codex-side action at the end of each chat
- a wrapper script that runs after transcript generation
- a desktop automation outside the repo

Without that trigger, the best available manual workflow is:

```bash
npm run sync:codex-chat
```

right after the transcript JSON has been updated.

## End-of-Chat Prompt

At the end of a Codex conversation, use this prompt:

```text
Please update `codex-chat-transcript.json` so it includes this full conversation, then run `npm run sync:codex-chat` to upload it to the dev Supabase `codex_chat_transcripts` table with a fresh context summary. After it finishes, tell me the `chat_key`, `message_count`, and whether the upload succeeded.
```

Short version:

```text
Update the local transcript with this full chat, then run `npm run sync:codex-chat` and confirm the upload to `codex_chat_transcripts`.
```

This works best as the final prompt in the thread, because it tells Codex to do both required steps:

1. Refresh the local transcript JSON so it includes the full conversation.
2. Generate the context summary and upload the row to `FWM_Dev`.

## Expected Confirmation

After a successful sync, Codex should report:

- `chat_key`
- `message_count`
- whether the upload succeeded

The upload script itself returns a JSON result with fields like:

```json
{
  "ok": true,
  "chat_key": "codex-...",
  "message_count": 71,
  "title": "Codex Chat Transcript",
  "summary_model": "gpt-5.2",
  "context_summary": "..."
}
```

For the closest thing to automatic syncing without browser automation, run:

```bash
npm run watch:codex-chat
```

Leave that watcher running during a session. Whenever `codex-chat-transcript.json` is updated or replaced, it reruns the upload and upserts the transcript row.

## Dev-Only Schema Source

This table belongs only in `FWM_Dev`.

The canonical SQL now lives here:

```text
supabase/dev-migrations/20260423000000_add_codex_chat_transcripts.sql
```

It is intentionally not stored in `supabase/migrations`, so a normal production migration push will not recreate it.

If you ever need to recreate this table in `FWM_Dev`, use that SQL file as the source of truth and apply it only to the dev project.
