-- Dev-only: database webhook — fire the notify-submission Edge Function on every
-- new pending submission so the operator gets an email with one-tap Approve/Reject.
--
-- Implemented as an AFTER INSERT trigger that does an async net.http_post (pg_net)
-- to the function URL. The Authorization bearer is the PUBLIC anon key (same one
-- shipped in config.dev.js) — it only has to be a valid JWT so the function's
-- verify_jwt passes; the function then re-fetches the row with the service role
-- and the Approve/Reject links are HMAC-signed, so nothing sensitive rides here.
--
-- The trigger swallows errors (raise warning, not exception) so a notification
-- hiccup can never block or roll back a user's submission insert. net.http_post is
-- async (queued by pg_net) so it doesn't add latency to the insert either.
--
-- Idempotent: CREATE EXTENSION IF NOT EXISTS, CREATE OR REPLACE, DROP TRIGGER IF
-- EXISTS before CREATE. Dev-only; prod needs its own (prod URL + prod anon key).

create extension if not exists pg_net;

create or replace function public.notify_review_submission()
returns trigger
language plpgsql
security definer
set search_path to 'pg_catalog', 'public'
as $function$
begin
  perform net.http_post(
    url := 'https://gosqgqpftqlawvnyelkt.supabase.co/functions/v1/notify-submission',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imdvc3FncXBmdHFsYXd2bnllbGt0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY2Mjc2NDMsImV4cCI6MjA5MjIwMzY0M30.EbjcaJDchbXkRQOYve0QzhYS67ShYW0X1RMAE2skbSo'
    ),
    body := jsonb_build_object(
      'type', 'INSERT',
      'record', jsonb_build_object('id', new.id)
    )
  );
  return new;
exception when others then
  raise warning 'notify_review_submission failed: %', sqlerrm;
  return new;
end;
$function$;

drop trigger if exists trg_notify_review_submission on public.user_review_submissions;
create trigger trg_notify_review_submission
  after insert on public.user_review_submissions
  for each row
  execute function public.notify_review_submission();
