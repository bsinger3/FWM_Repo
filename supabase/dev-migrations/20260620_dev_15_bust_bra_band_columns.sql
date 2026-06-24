-- Add separate bust circumference and bra band columns to public.images.
-- Previously only bust_in_number_display (legacy conflated) and cupsize_display
-- existed. This separates them so a "32B" bra size is stored as
-- bra_band_in_display=32, cupsize_display='B', while an explicit "bust is 42
-- inches" measurement is stored in bust_in_display=42.

alter table public.images
  add column if not exists bust_in_display numeric,
  add column if not exists bra_band_in_display numeric;

comment on column public.images.bust_in_display is
  'Actual bust circumference in inches, from free-text review comment (e.g. "my bust is 42 inches"). Null when not stated.';

comment on column public.images.bra_band_in_display is
  'Bra band size in inches extracted from a bra size string (e.g. "32B" -> 32) or explicit underbust measurement. Null when not stated.';

-- Update the loader RPC to accept and write all four bust/bra fields.
create or replace function public.dev_upsert_reviewed_image_batch(payload jsonb)
returns table (
  input_count integer,
  product_pages_upserted integer,
  reviews_upserted integer,
  images_inserted integer,
  images_updated integer
)
language plpgsql
security definer
set search_path = public, staging
as $function$
declare
  product_page_count integer := 0;
  review_count integer := 0;
  inserted_count integer := 0;
  updated_count integer := 0;
begin
  if payload is null or jsonb_typeof(payload) <> 'array' then
    raise exception 'payload must be a jsonb array';
  end if;

  create temporary table tmp_reviewed_image_load (
    action text not null,
    image_id uuid,
    baseline_image_id uuid,
    image_url text not null,
    normalized_product_page_url text not null,
    monetized_product_url text,
    source_site text,
    brand text,
    product_title_raw text,
    product_category_raw text,
    clothing_type_id text,
    review_identity_key text not null,
    source_review_id text,
    reviewer_name_raw text,
    review_date_raw text,
    user_comment text,
    source_file text,
    source_row_number text,
    review_row_key text not null,
    crop_spec jsonb,
    full_body_visible boolean,
    weeks_pregnant integer,
    pregnancy_evidence text,
    height_in_display numeric,
    weight_lbs_display numeric,
    waist_in numeric,
    hips_in_display numeric,
    inseam_inches_display numeric,
    bust_in_display numeric,
    bra_band_in_display numeric,
    bust_in_number_display integer,
    cupsize_display text,
    size_display text
  ) on commit drop;

  insert into tmp_reviewed_image_load
  select *
  from jsonb_to_recordset(payload) as row_data (
    action text,
    image_id uuid,
    baseline_image_id uuid,
    image_url text,
    normalized_product_page_url text,
    monetized_product_url text,
    source_site text,
    brand text,
    product_title_raw text,
    product_category_raw text,
    clothing_type_id text,
    review_identity_key text,
    source_review_id text,
    reviewer_name_raw text,
    review_date_raw text,
    user_comment text,
    source_file text,
    source_row_number text,
    review_row_key text,
    crop_spec jsonb,
    full_body_visible boolean,
    weeks_pregnant integer,
    pregnancy_evidence text,
    height_in_display numeric,
    weight_lbs_display numeric,
    waist_in numeric,
    hips_in_display numeric,
    inseam_inches_display numeric,
    bust_in_display numeric,
    bra_band_in_display numeric,
    bust_in_number_display integer,
    cupsize_display text,
    size_display text
  );

  if exists (
    select 1
    from tmp_reviewed_image_load
    where action not in ('insert', 'merge_into_baseline')
       or nullif(image_url, '') is null
       or nullif(normalized_product_page_url, '') is null
       or nullif(review_identity_key, '') is null
       or nullif(review_row_key, '') is null
       or (action = 'insert' and image_id is null)
       or (action = 'merge_into_baseline' and baseline_image_id is null)
  ) then
    raise exception 'payload contains unsupported actions or missing required fields';
  end if;

  insert into staging.product_pages (
    normalized_product_page_url,
    source_site,
    brand,
    product_title_raw,
    product_category_raw,
    observed_clothing_type_ids,
    image_row_count,
    first_seen_at,
    last_seen_at,
    populated_from,
    raw_metadata,
    updated_at
  )
  select
    normalized_product_page_url,
    max(nullif(source_site, '')),
    max(nullif(brand, '')),
    max(nullif(product_title_raw, '')),
    max(nullif(product_category_raw, '')),
    coalesce(array_agg(distinct clothing_type_id) filter (where clothing_type_id is not null), '{}'::text[]),
    0,
    now(),
    now(),
    'approved_review_loader',
    jsonb_build_object('loader', 'dev_upsert_reviewed_image_batch'),
    now()
  from tmp_reviewed_image_load
  group by normalized_product_page_url
  on conflict (normalized_product_page_url) do update
  set
    source_site = coalesce(excluded.source_site, staging.product_pages.source_site),
    brand = coalesce(excluded.brand, staging.product_pages.brand),
    product_title_raw = coalesce(excluded.product_title_raw, staging.product_pages.product_title_raw),
    product_category_raw = coalesce(excluded.product_category_raw, staging.product_pages.product_category_raw),
    observed_clothing_type_ids = coalesce((
      select array_agg(distinct value order by value)
      from unnest(staging.product_pages.observed_clothing_type_ids || excluded.observed_clothing_type_ids) as value
      where value is not null
    ), '{}'::text[]),
    image_row_count = staging.product_pages.image_row_count,
    last_seen_at = now(),
    raw_metadata = staging.product_pages.raw_metadata || excluded.raw_metadata,
    updated_at = now();
  get diagnostics product_page_count = row_count;

  insert into public.reviews (
    product_page_id,
    normalized_product_page_url,
    source_site,
    source_review_id,
    review_identity_key,
    reviewer_name_raw,
    review_date_raw,
    user_comment,
    source_file,
    source_row_number,
    updated_at
  )
  select distinct on (load.review_identity_key)
    page.id,
    load.normalized_product_page_url,
    nullif(load.source_site, ''),
    nullif(load.source_review_id, ''),
    load.review_identity_key,
    nullif(load.reviewer_name_raw, ''),
    nullif(load.review_date_raw, ''),
    nullif(load.user_comment, ''),
    nullif(load.source_file, ''),
    nullif(load.source_row_number, ''),
    now()
  from tmp_reviewed_image_load load
  join staging.product_pages page
    on page.normalized_product_page_url = load.normalized_product_page_url
  order by load.review_identity_key, load.review_row_key
  on conflict (review_identity_key) do update
  set
    product_page_id = excluded.product_page_id,
    normalized_product_page_url = excluded.normalized_product_page_url,
    source_site = coalesce(excluded.source_site, public.reviews.source_site),
    source_review_id = coalesce(excluded.source_review_id, public.reviews.source_review_id),
    reviewer_name_raw = coalesce(excluded.reviewer_name_raw, public.reviews.reviewer_name_raw),
    review_date_raw = coalesce(excluded.review_date_raw, public.reviews.review_date_raw),
    user_comment = coalesce(excluded.user_comment, public.reviews.user_comment),
    source_file = coalesce(excluded.source_file, public.reviews.source_file),
    source_row_number = coalesce(excluded.source_row_number, public.reviews.source_row_number),
    updated_at = now();
  get diagnostics review_count = row_count;

  insert into public.images (
    id,
    original_url_display,
    product_page_url_display,
    monetized_product_url_display,
    user_comment,
    date_review_submitted_raw,
    height_in_display,
    weight_lb,
    weight_lbs_display,
    waist_in,
    hips_in_display,
    inseam_inches_display,
    bust_in_display,
    bra_band_in_display,
    bust_in_number_display,
    cupsize_display,
    source_site_display,
    brand,
    clothing_type_id,
    reviewer_name_raw,
    size_display,
    review_id,
    product_page_id,
    review_row_key,
    source_file,
    source_row_number,
    crop_spec,
    full_body_visible,
    weeks_pregnant,
    pregnancy_evidence,
    created_at_display,
    updated_at
  )
  select
    load.image_id,
    load.image_url,
    load.normalized_product_page_url,
    nullif(load.monetized_product_url, ''),
    nullif(load.user_comment, ''),
    nullif(load.review_date_raw, ''),
    load.height_in_display,
    load.weight_lbs_display,
    load.weight_lbs_display,
    load.waist_in,
    load.hips_in_display,
    load.inseam_inches_display,
    load.bust_in_display,
    load.bra_band_in_display,
    load.bust_in_number_display,
    nullif(load.cupsize_display, ''),
    nullif(load.source_site, ''),
    nullif(load.brand, ''),
    nullif(load.clothing_type_id, ''),
    nullif(load.reviewer_name_raw, ''),
    coalesce(nullif(load.size_display, ''), 'unknown'),
    review.id,
    page.id,
    load.review_row_key,
    nullif(load.source_file, ''),
    nullif(load.source_row_number, ''),
    load.crop_spec,
    load.full_body_visible,
    load.weeks_pregnant,
    nullif(load.pregnancy_evidence, ''),
    now(),
    now()
  from tmp_reviewed_image_load load
  join staging.product_pages page
    on page.normalized_product_page_url = load.normalized_product_page_url
  join public.reviews review
    on review.review_identity_key = load.review_identity_key
  where load.action = 'insert'
  on conflict (review_row_key) where review_row_key is not null do update
  set
    review_id = excluded.review_id,
    product_page_id = excluded.product_page_id,
    source_file = excluded.source_file,
    source_row_number = excluded.source_row_number,
    crop_spec = excluded.crop_spec,
    full_body_visible = excluded.full_body_visible,
    weeks_pregnant = excluded.weeks_pregnant,
    pregnancy_evidence = excluded.pregnancy_evidence,
    updated_at = now();
  get diagnostics inserted_count = row_count;

  update public.images image
  set
    review_id = review.id,
    product_page_id = page.id,
    review_row_key = load.review_row_key,
    source_file = nullif(load.source_file, ''),
    source_row_number = nullif(load.source_row_number, ''),
    crop_spec = load.crop_spec,
    full_body_visible = load.full_body_visible,
    weeks_pregnant = load.weeks_pregnant,
    pregnancy_evidence = nullif(load.pregnancy_evidence, ''),
    updated_at = now()
  from tmp_reviewed_image_load load
  join staging.product_pages page
    on page.normalized_product_page_url = load.normalized_product_page_url
  join public.reviews review
    on review.review_identity_key = load.review_identity_key
  where load.action = 'merge_into_baseline'
    and image.id = load.baseline_image_id;
  get diagnostics updated_count = row_count;

  update staging.product_pages page
  set
    image_row_count = coalesce(counts.image_count, 0),
    last_seen_at = now(),
    updated_at = now()
  from (
    select
      touched.normalized_product_page_url,
      count(image.id)::integer as image_count
    from (
      select distinct normalized_product_page_url
      from tmp_reviewed_image_load
    ) touched
    join staging.product_pages page_for_count
      on page_for_count.normalized_product_page_url = touched.normalized_product_page_url
    left join public.images image
      on image.product_page_id = page_for_count.id
    group by touched.normalized_product_page_url
  ) counts
  where page.normalized_product_page_url = counts.normalized_product_page_url;

  return query
  select
    (select count(*)::integer from tmp_reviewed_image_load),
    product_page_count,
    review_count,
    inserted_count,
    updated_count;
end;
$function$;

revoke all on function public.dev_upsert_reviewed_image_batch(jsonb) from public;
grant execute on function public.dev_upsert_reviewed_image_batch(jsonb) to service_role;
