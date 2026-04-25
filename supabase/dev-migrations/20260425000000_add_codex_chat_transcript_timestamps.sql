-- Dev-only migration: add conversation timing columns to codex_chat_transcripts
-- Applies only to the FWM_Dev Supabase project.
-- Do not copy this into shared production migrations.

ALTER TABLE codex_chat_transcripts
  ADD COLUMN IF NOT EXISTS transcript_started_at timestamptz,
  ADD COLUMN IF NOT EXISTS transcript_ended_at timestamptz;
