# Codex Chat Transcript Archiving

This repo can archive full Codex chat transcripts into Supabase and generate a structured context summary for each chat.

## What This Adds

- A private dev-only Supabase table: `codex_chat_transcripts`
- A local upload script:

```bash
node scripts/upload-codex-chat-transcript.mjs /path/to/session-transcript.json
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

1. Reads the transcript JSON path passed on the command line, or the path in
   `FWM_TRANSCRIPT_PATH`
2. Resolves conversation start/end timestamps from transcript metadata when available
3. Builds a `full_text` version from all messages
4. Uses the OpenAI Responses API to generate a structured context summary
5. Computes a deterministic `chat_key`
6. Upserts the transcript into `codex_chat_transcripts`

It also handles slightly richer transcript message shapes than plain `{ role, text }`, so a future export with nested `content` still gets flattened into `full_text`.

For timing, the uploader looks first for top-level or `metadata` fields such as:

```json
{
  "transcript_started_at": "2026-04-23T16:42:11-04:00",
  "transcript_ended_at": "2026-04-25T11:00:00-04:00"
}
```

If those are missing, it falls back to any per-message timestamps it can find, then to the transcript file's filesystem timestamps as a best effort.

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

If a full desktop transcript export is not available, create a focused handoff transcript JSON for the current session and upload that file with:

```bash
node scripts/upload-codex-chat-transcript.mjs path/to/session-transcript.json
```

The handoff transcript should include the user requests, major assistant actions, verification results, changed files, blockers, and next steps. It is not a perfect replacement for a full chat export, but it is still useful durable project memory for the next Codex session.

## Focused Handoff Transcripts

| File | Date | Scope |
| --- | --- | --- |
| `codex-swimoutlet-scrape-resume-transcript-2026-05-07.json` | 2026-05-07 | SwimOutlet checkpointed non-Amazon scrape resume: products.json boundary, sitemap discovery, Okendo store-review checkpoint, final bounded CSV/summary, and claim update. |
| `codex-nonamazon-liverpool-vs-aliava-transcript-2026-05-06.json` | 2026-05-06 | Liverpool Style refresh, Victoria's Secret workbook conversion, blocked-site triage, and Aliava catalog-model scrape. |

## End-of-Chat Prompt

At the end of a Codex conversation, use this prompt:

```text
Please write the temporary transcript JSON outside the repo root, then run
`node scripts/upload-codex-chat-transcript.mjs /path/to/session-transcript.json`
to upload it to the dev Supabase `codex_chat_transcripts` table with a fresh
context summary. After it finishes, tell me the `chat_key`, `message_count`,
and whether the upload succeeded.
```

Short version:

```text
Update a temporary transcript JSON outside the repo root, upload it with
`scripts/upload-codex-chat-transcript.mjs`, and confirm the upload to
`codex_chat_transcripts`.
```

This works best as the final prompt in the thread, because it tells Codex to do both required steps:

1. Refresh the local transcript JSON so it includes the full conversation.
2. Generate the context summary and upload the row to `FWM_Dev`.

## Expected Confirmation

After a successful sync, Codex should report:

- `chat_key`
- `message_count`
- `transcript_started_at`
- `transcript_ended_at`
- whether the upload succeeded

The upload script itself returns a JSON result with fields like:

```json
{
  "ok": true,
  "chat_key": "codex-...",
  "message_count": 71,
  "title": "Codex Chat Transcript",
  "transcript_started_at": "2026-04-23T16:42:11.000Z",
  "transcript_ended_at": "2026-04-25T15:00:00.000Z",
  "summary_model": "gpt-5.2",
  "context_summary": "..."
}
```

For the closest thing to automatic syncing without browser automation, run:

```bash
npm run watch:codex-chat
```

Leave that watcher running during a session. Whenever the explicit transcript
path is updated or replaced, it reruns the upload and upserts the transcript
row. Do not keep watcher input files in the repo root.

## Dev-Only Schema Source

This table belongs only in `FWM_Dev`.

The canonical SQL now lives here:

```text
supabase/dev-migrations/20260423000000_add_codex_chat_transcripts.sql
```

It is intentionally not stored in `supabase/migrations`, so a normal production migration push will not recreate it.

If you ever need to recreate this table in `FWM_Dev`, use that SQL file as the source of truth and apply it only to the dev project.
