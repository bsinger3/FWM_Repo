-- Security hardening for the gosqg -> production cutover.
--
-- A `default_anon_read_public_<table>` policy (SELECT to anon,authenticated
-- USING true) had been auto-added to 13 tables, making them publicly readable
-- over the anon REST API. That exposed private data — the operator's Claude
-- conversation archive (codex_chat_transcripts + the altr_/applypilot_/
-- guy_carpenter_ variants), analytics (search_events, product_card_events),
-- image_reports, reviews, and a latent one on user_review_submissions (the
-- email/PII table — currently inert only because dev_33 revoked anon's SELECT
-- grant, but the policy shouldn't exist).
--
-- The storefront reads images / clothing_types / clothing_mother_categories via
-- the explicit dev_36 policies (NOT these default ones), so dropping every
-- default_anon_read policy does not affect the catalog. Anon INSERT policies for
-- event tracking + review submission are named differently and are untouched.
-- Transcript tables keep their service_role policies (used by
-- scripts/upload-codex-chat-transcript.mjs), so the save path still works.

-- 1) Drop every auto-added anon-read policy, in any schema.
do $$
declare r record;
begin
  for r in
    select schemaname, tablename, policyname
    from pg_policies
    where policyname like 'default_anon_read%'
  loop
    execute format('drop policy if exists %I on %I.%I', r.policyname, r.schemaname, r.tablename);
  end loop;
end $$;

-- 2) Belt-and-suspenders: strip anon/authenticated grants from the private,
--    non-storefront tables so they're reachable only by service_role.
revoke all on public.codex_chat_transcripts             from anon, authenticated;
revoke all on public.altr_codex_chat_transcripts        from anon, authenticated;
revoke all on public.applypilot_codex_chat_transcripts  from anon, authenticated;
revoke all on public.guy_carpenter_codex_chat_transcripts from anon, authenticated;
revoke all on public.work_transcript_classification_notes from anon, authenticated;
revoke all on public.images_backup_20260320             from anon, authenticated;
revoke all on public.images_staging                     from anon, authenticated;

-- 3) Analytics/report tables: anon may INSERT (tracking) but not read/modify.
revoke all on public.search_events        from anon, authenticated;
revoke all on public.product_card_events  from anon, authenticated;
revoke all on public.image_reports        from anon, authenticated;
grant insert on public.search_events        to anon, authenticated;
grant insert on public.product_card_events  to anon, authenticated;
grant insert on public.image_reports        to anon, authenticated;
