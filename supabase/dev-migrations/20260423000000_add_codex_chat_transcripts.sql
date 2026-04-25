-- Dev-only migration: add_codex_chat_transcripts
-- Applies only to the FWM_Dev Supabase project.
-- Do not copy this into shared production migrations.

CREATE TABLE codex_chat_transcripts (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_key             text NOT NULL UNIQUE,
  source               text NOT NULL DEFAULT 'codex',
  title                text,
  transcript_started_at timestamptz,
  transcript_ended_at   timestamptz,
  transcript_json      jsonb NOT NULL,
  full_text            text NOT NULL,
  context_summary      text,
  context_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  message_count        integer NOT NULL DEFAULT 0,
  local_file_path      text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_codex_chat_transcripts_source_created_at
  ON codex_chat_transcripts(source, created_at DESC);

ALTER TABLE codex_chat_transcripts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role can insert chat transcripts"
  ON codex_chat_transcripts
  FOR INSERT
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Service role can update chat transcripts"
  ON codex_chat_transcripts
  FOR UPDATE
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "Service role can read chat transcripts"
  ON codex_chat_transcripts
  FOR SELECT
  USING (auth.role() = 'service_role');
