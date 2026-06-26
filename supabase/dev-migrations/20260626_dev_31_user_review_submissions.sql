-- Dev-only: PLUMBING for user-submitted reviews ("Submit your own review").
--
-- Adds a holding-pen table that captures EVERYTHING a shopper types about a
-- product plus the storage paths of the photos they upload. Submissions land as
-- status='pending' and do NOT touch search until an operator approves them; on
-- approval a separate script promotes a row into reviews + images + product_pages
-- (those image rows get is_fwm_user_content=true). Nothing in search reads this
-- table, so a malicious self-set status is inert — but we still force anon
-- inserts to be 'pending' via the RLS WITH CHECK.
--
-- Mirrors the established anon-insert pattern used by public.image_reports and
-- public.product_card_events: RLS on, "anyone can INSERT", "service_role can
-- read". The frontend already stamps FWM_ANON_ID / FWM_SESSION_ID on events;
-- those flow in here too.
--
-- Storage bucket + storage.objects policies are created in the next migration
-- (dev_32) so schema and storage concerns stay separable.
--
-- Idempotent: CREATE TABLE / ADD COLUMN IF NOT EXISTS, DROP POLICY IF EXISTS
-- before CREATE POLICY. dev-migrations/ applies to dev only; prod is untouched.

create table if not exists public.user_review_submissions (
  id                  uuid primary key default gen_random_uuid(),

  -- moderation state. Anon can only ever create 'pending' rows (enforced by the
  -- RLS WITH CHECK below); operator moves it to approved/rejected.
  status              text not null default 'pending'
                        check (status in ('pending', 'approved', 'rejected')),

  -- attribution (reuses the client's existing localStorage/sessionStorage ids)
  anon_id             text,
  session_id          text,
  submitted_at        timestamptz not null default now(),

  -- optional reviewer contact / identity
  reviewer_email      text,
  reviewer_name       text,

  -- ---- measurements (map onto public.images) -------------------------------
  -- Stored as the cleaned numeric values the client computes from the form
  -- (e.g. height_in_total = feet*12 + inches) so promotion is a straight copy.
  height_in_total     numeric,   -- -> images.height_in_display
  weight_lbs          numeric,   -- -> images.weight_lbs_display
  bra_band_in         numeric,   -- -> images.bra_band_in_display
  cup_size            text,      -- -> images.cupsize_display
  bust_full_in        numeric,   -- -> images.bust_in_display (full bust, not band)
  bust_in_number      integer,   -- -> images.bust_in_number_display
  waist_in            numeric,   -- -> images.waist_in
  hips_in             numeric,   -- -> images.hips_in_display
  inseam_in           numeric,   -- -> images.inseam_inches_display
  age_years           integer,   -- -> images.age_years_display
  weeks_pregnant      integer,   -- -> images.weeks_pregnant
  full_body_visible   boolean,   -- -> images.full_body_visible

  -- ---- product (map onto staging.product_pages + images) -------------------
  brand               text,
  product_page_url    text,      -- -> normalized to product_pages.normalized_product_page_url
  source_site         text,
  size_purchased      text,      -- REQUIRED downstream: images.size_display is NOT NULL
  color               text,
  price               text,
  mother_category_id  text,      -- high-level category the shopper picked

  -- ---- free text + photos --------------------------------------------------
  user_comment        text,
  -- storage paths within the review-uploads bucket (set in dev_32). Capped at 5.
  image_paths         text[] not null default '{}'
                        check (
                          array_length(image_paths, 1) is null
                          or array_length(image_paths, 1) <= 5
                        ),

  -- ---- moderation bookkeeping (filled in by the approval script) -----------
  reviewed_at         timestamptz,
  rejection_reason    text,
  promoted_review_id  uuid,      -- public.reviews(id) created on approval
  promoted_product_page_id uuid, -- staging.product_pages(id) linked on approval

  created_at          timestamptz not null default now()
);

create index if not exists idx_user_review_submissions_status
  on public.user_review_submissions(status);
create index if not exists idx_user_review_submissions_submitted_at
  on public.user_review_submissions(submitted_at desc);

alter table public.user_review_submissions enable row level security;

-- Anyone (anon) may submit, but ONLY as a pending row. They can never read the
-- table back (no SELECT policy for anon) so submissions aren't publicly listable.
drop policy if exists "Anyone can submit a review" on public.user_review_submissions;
create policy "Anyone can submit a review"
  on public.user_review_submissions
  for insert
  with check (status = 'pending');

drop policy if exists "Service role can read submissions" on public.user_review_submissions;
create policy "Service role can read submissions"
  on public.user_review_submissions
  for select
  using (auth.role() = 'service_role');

drop policy if exists "Service role can update submissions" on public.user_review_submissions;
create policy "Service role can update submissions"
  on public.user_review_submissions
  for update
  using (auth.role() = 'service_role');

-- Explicit grants (Supabase default privileges usually cover this, but be safe).
grant insert on public.user_review_submissions to anon, authenticated;
grant select, update on public.user_review_submissions to service_role;

-- ---- provenance on public.images -------------------------------------------
-- Flags rows that originated from a user submission (vs the scraping pipeline),
-- and links back to the submission they came from.
alter table public.images
  add column if not exists is_fwm_user_content boolean not null default false;
alter table public.images
  add column if not exists user_submission_id uuid;

create index if not exists idx_images_is_fwm_user_content
  on public.images(is_fwm_user_content)
  where is_fwm_user_content = true;
