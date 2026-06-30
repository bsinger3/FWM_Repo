-- Dev-only: server-side promotion/rejection of user review submissions, as
-- atomic SECURITY DEFINER functions so BOTH the moderate-submission Edge Function
-- and scripts/approve-review-submission.mjs can share one implementation (no
-- drift between the email one-tap path and the CLI).
--
-- approve_user_submission(id, storage_base_url):
--   find-or-create staging.product_pages (by normalized url) -> insert 1
--   public.reviews -> insert 1 public.images per uploaded photo
--   (is_fwm_user_content=true, original_url_display = public storage URL) ->
--   mark the submission approved. Returns json {review_id, product_page_id,
--   image_count}. Refuses unless status='pending' (idempotent re-promote guard)
--   and unless size_purchased is present (images.size_display is NOT NULL).
--   Does NOT refresh searchable_images (a matview refresh can't be the concern of
--   the promotion txn) — callers run refresh_searchable_images() after.
--
-- reject_user_submission(id, reason): mark rejected, create no live rows.
--
-- refresh_searchable_images(): non-concurrent refresh (safe inside a function;
--   CONCURRENTLY is not). Brief lock; fine for an admin-triggered approval.
--
-- storage_base_url is passed in (not hardcoded) so the same function works in dev
-- and prod — the Edge Function passes its SUPABASE_URL, the CLI passes the guard's.
--
-- Idempotent: CREATE OR REPLACE. EXECUTE granted to service_role only (the Edge
-- Function uses the service role; the CLI connects as the owner and bypasses).

create or replace function public.approve_user_submission(
  p_submission_id uuid,
  p_storage_base_url text
)
returns json
language plpgsql
security definer
set search_path to 'pg_catalog', 'public', 'staging'
as $function$
declare
  v_sub          public.user_review_submissions%rowtype;
  v_norm_url     text;
  v_identity_key text;
  v_page_id      uuid;
  v_review_id    uuid;
  v_image_count  integer := 0;
begin
  select * into v_sub
    from public.user_review_submissions
    where id = p_submission_id
    for update;

  if not found then
    raise exception 'No submission found with id %', p_submission_id;
  end if;
  if v_sub.status <> 'pending' then
    raise exception 'Submission % is status=%, not pending; refusing to re-promote',
      p_submission_id, v_sub.status;
  end if;
  if v_sub.size_purchased is null or btrim(v_sub.size_purchased) = '' then
    raise exception 'Submission % has no size_purchased, but images.size_display is NOT NULL', p_submission_id;
  end if;
  if v_sub.product_page_url is null or btrim(v_sub.product_page_url) = '' then
    raise exception 'Submission % has no product_page_url; cannot resolve a product page', p_submission_id;
  end if;

  v_norm_url     := staging.normalize_product_url(v_sub.product_page_url);
  v_identity_key := 'user_submission:' || p_submission_id::text;

  if exists (select 1 from public.reviews where review_identity_key = v_identity_key) then
    raise exception 'A review with identity key % already exists; submission status may be out of sync',
      v_identity_key;
  end if;

  -- 1) find-or-create the product page (UNIQUE normalized_product_page_url)
  insert into staging.product_pages (
    normalized_product_page_url, brand, source_site, mother_category_id,
    category_confidence, needs_manual_review, populated_from
  )
  values (
    v_norm_url, v_sub.brand, v_sub.source_site, v_sub.mother_category_id,
    'low', true, 'user_submission'
  )
  on conflict (normalized_product_page_url) do update set updated_at = now()
  returning id into v_page_id;

  -- 2) one review
  insert into public.reviews (
    product_page_id, normalized_product_page_url, review_identity_key,
    source_site, reviewer_name_raw, user_comment, source_file
  )
  values (
    v_page_id, v_norm_url, v_identity_key,
    v_sub.source_site, v_sub.reviewer_name, v_sub.user_comment,
    'user_review_submissions:' || p_submission_id::text
  )
  returning id into v_review_id;

  -- 3) one image per uploaded photo; original_url_display = public storage URL
  insert into public.images (
    id, product_page_id, review_id, user_submission_id, is_fwm_user_content,
    original_url_display, product_page_url_display,
    height_in_display, weight_lbs_display, bra_band_in_display, bust_in_display,
    bust_in_number_display, cupsize_display, waist_in, hips_in_display,
    inseam_inches_display, age_years_display, weeks_pregnant, full_body_visible,
    brand, source_site_display, size_display, color_display, mother_category_id,
    reviewer_name_raw, user_comment
  )
  select
    gen_random_uuid(), v_page_id, v_review_id, p_submission_id, true,
    p_storage_base_url || '/storage/v1/object/public/review-uploads/' || pth,
    v_sub.product_page_url,
    v_sub.height_in_total, v_sub.weight_lbs, v_sub.bra_band_in, v_sub.bust_full_in,
    v_sub.bust_in_number, v_sub.cup_size, v_sub.waist_in::text, v_sub.hips_in,
    v_sub.inseam_in, v_sub.age_years, v_sub.weeks_pregnant, v_sub.full_body_visible,
    v_sub.brand, v_sub.source_site, v_sub.size_purchased, v_sub.color, v_sub.mother_category_id,
    v_sub.reviewer_name, v_sub.user_comment
  from unnest(coalesce(v_sub.image_paths, array[]::text[])) as pth;
  get diagnostics v_image_count = row_count;

  -- 4) mark approved + back-link
  update public.user_review_submissions
    set status = 'approved',
        reviewed_at = now(),
        promoted_review_id = v_review_id,
        promoted_product_page_id = v_page_id
    where id = p_submission_id;

  return json_build_object(
    'review_id', v_review_id,
    'product_page_id', v_page_id,
    'image_count', v_image_count
  );
end;
$function$;

create or replace function public.reject_user_submission(
  p_submission_id uuid,
  p_reason text
)
returns json
language plpgsql
security definer
set search_path to 'pg_catalog', 'public', 'staging'
as $function$
declare
  v_status text;
begin
  select status into v_status
    from public.user_review_submissions
    where id = p_submission_id
    for update;

  if not found then
    raise exception 'No submission found with id %', p_submission_id;
  end if;
  if v_status <> 'pending' then
    raise exception 'Submission % is status=%, not pending; refusing to reject',
      p_submission_id, v_status;
  end if;

  update public.user_review_submissions
    set status = 'rejected',
        reviewed_at = now(),
        rejection_reason = p_reason
    where id = p_submission_id;

  return json_build_object('submission_id', p_submission_id, 'status', 'rejected');
end;
$function$;

create or replace function public.refresh_searchable_images()
returns void
language plpgsql
security definer
set search_path to 'pg_catalog', 'public'
as $function$
begin
  -- Non-concurrent: allowed inside a function (CONCURRENTLY is not). Brief
  -- ACCESS EXCLUSIVE lock; acceptable for an occasional admin approval.
  refresh materialized view public.searchable_images;
end;
$function$;

-- Lock down EXECUTE to service_role only (Edge Function uses it; the CLI runs as
-- the table owner and bypasses). Never expose these to anon/authenticated.
revoke all on function public.approve_user_submission(uuid, text) from public, anon, authenticated;
revoke all on function public.reject_user_submission(uuid, text) from public, anon, authenticated;
revoke all on function public.refresh_searchable_images() from public, anon, authenticated;
grant execute on function public.approve_user_submission(uuid, text) to service_role;
grant execute on function public.reject_user_submission(uuid, text) to service_role;
grant execute on function public.refresh_searchable_images() to service_role;
