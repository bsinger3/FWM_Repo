-- Dev-only: HARDEN the PII-bearing user_review_submissions table.
--
-- This table holds reviewer_email (and name) — personal data. RLS is already on
-- (dev_31): anon/authenticated have NO select policy, so they can't read any row.
-- That works, but it's single-layer: Supabase's default privileges still GRANT
-- anon + authenticated full SELECT/UPDATE/DELETE on the table, so RLS is the only
-- thing between the public and those emails. If RLS were ever disabled or a
-- permissive policy added, the PII would leak.
--
-- Defense in depth: revoke every privilege from anon/authenticated EXCEPT insert,
-- so the read/modify privilege simply doesn't exist for public roles. The
-- frontend only ever INSERTs (no .select() on the response), so this is invisible
-- to users. service_role and the owner (postgres) keep full access — that's how
-- the operator + approval script read/moderate submissions.
--
-- NOT using FORCE ROW LEVEL SECURITY on purpose: the table owner is `postgres`,
-- and scripts/approve-review-submission.mjs connects AS the owner and relies on
-- the owner bypassing RLS to read/promote submissions. Forcing RLS would subject
-- the owner to the service_role policy (which checks a JWT claim that a direct
-- psql connection doesn't carry) and break moderation. Grant-tightening gives the
-- protection without that risk.
--
-- Idempotent: REVOKE/GRANT are repeatable.

-- Remove the broad default privileges from the public-facing roles.
revoke all privileges on public.user_review_submissions from anon, authenticated;

-- Re-grant ONLY what the public submit form needs: insert a (pending) row.
grant insert on public.user_review_submissions to anon, authenticated;

-- Belt-and-suspenders: nothing should be granted to the PUBLIC pseudo-role.
revoke all privileges on public.user_review_submissions from public;

-- service_role moderates (read + update); keep it explicit and intact.
grant select, update, insert on public.user_review_submissions to service_role;

-- NOTE: this fixes THIS table only. Supabase's ALTER DEFAULT PRIVILEGES still
-- grants all to anon/authenticated on future public tables — the prod port of
-- this feature must apply the same revoke there.
