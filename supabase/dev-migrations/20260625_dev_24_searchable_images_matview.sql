-- Dev-only: make match_by_measurements fast enough for the anon 3s timeout.
--
-- Problem: every search did a full seq scan of public.images (~46k rows),
-- ran regexp_replace() on waist_in twice per row, and anti-joined
-- staging.product_pages + image_reports — ~2.0-2.7s warm, which blows past
-- the anon role's 3s statement_timeout on a cold connection. The measurement
-- inputs only feed the *ordering* score, never a selective WHERE, so no index
-- could help: the work was inherent to scanning + transforming every row on
-- every query.
--
-- Fix: precompute the static eligibility + the regexp-derived columns once into
-- a materialized view (public.searchable_images). At query time the function
-- scans that smaller, already-cleaned set, scores, sorts, and limits. Measured:
-- score+sort+limit over the precomputed set ran in ~90ms vs ~2685ms.
--
-- What stays LIVE in the function (not baked into the MV):
--   * the image_reports 'dead_link' exclusion — so flagging an image hides it
--     immediately without a refresh (it's a cheap, indexed anti-join).
-- What is baked into the MV (refresh when these change):
--   * row-intrinsic eligibility (has a usable size, a product URL, at least one
--     measurement, a live source image)
--   * the staging.product_pages dead/unavailable exclusion (changes rarely, only
--     via backfills)
--   * waist_in_numeric and cupsize_display_normalized (the regexp/normalize work)
--
-- Refresh after image loads or product_pages.source_status changes with:
--   refresh materialized view concurrently public.searchable_images;
-- (concurrent refresh is enabled by the unique index on id below.)

drop materialized view if exists public.searchable_images;

create materialized view public.searchable_images as
  select
    i.id,
    i.original_url_display,
    i.product_page_url_display,
    i.monetized_product_url_display,
    i.brand,
    i.source_site_display,
    i.height_in_display,
    i.weight_display_display,
    i.size_display,
    i.color_display,
    i.bust_in_number_display,
    i.cupsize_display,
    i.waist_in,
    i.hips_in_display,
    i.inseam_inches_display,
    i.age_years_display,
    i.crop_spec,
    i.review_id,
    i.product_page_id,
    i.full_body_visible,
    i.weeks_pregnant,
    i.prettiness_score,
    i.mother_category_id,
    -- needed for scoring / require-windows
    i.weight_lbs_display,
    i.created_at_display,
    -- precomputed (no regexp at query time)
    nullif(regexp_replace(coalesce(i.waist_in, ''), '[^0-9.]', '', 'g'), '')::numeric
      as waist_in_numeric,
    nullif(upper(btrim(i.cupsize_display)), '') as cupsize_display_normalized
  from public.images i
  where
    i.original_url_display is not null
    -- drop images whose product page is known-dead/unavailable.
    and not exists (
      select 1
      from staging.product_pages pp
      where pp.id = i.product_page_id
        and pp.source_status in ('page_not_found', 'product_unavailable', 'redirected_to_non_product')
    )
    and (i.size_display is not null and btrim(i.size_display) <> '' and lower(btrim(i.size_display)) <> 'unknown')
    and (i.monetized_product_url_display is not null or i.product_page_url_display is not null)
    and (
      i.height_in_display is not null
      or i.weight_lbs_display is not null
      or i.bust_in_number_display is not null
      or i.hips_in_display is not null
      or nullif(regexp_replace(coalesce(i.waist_in, ''), '[^0-9.]', '', 'g'), '') is not null
      or nullif(upper(btrim(i.cupsize_display)), '') is not null
    );

-- Unique index enables REFRESH MATERIALIZED VIEW CONCURRENTLY.
create unique index if not exists searchable_images_id_idx
  on public.searchable_images (id);
-- Speeds up the clothing-type (mother category) filter.
create index if not exists searchable_images_mother_idx
  on public.searchable_images (mother_category_id);

-- NOTE: intentionally NOT granting SELECT to anon/authenticated. The function is
-- SECURITY DEFINER and reads the MV as its owner, so the MV stays off the public
-- PostgREST API surface.

-- Drop first: the return shape gains a total_count column below, and
-- CREATE OR REPLACE cannot change a function's return type.
drop function if exists public.match_by_measurements(
  text, numeric, numeric, numeric, numeric, text, numeric,
  boolean, boolean, boolean, boolean, boolean, integer, integer
);

create or replace function public.match_by_measurements(
  in_clothing_type_id text default null,
  in_height numeric default null,
  in_hips numeric default null,
  in_weight numeric default null,
  in_bust numeric default null,
  in_cup_size text default null,
  in_waist numeric default null,
  require_height boolean default false,
  require_hips boolean default false,
  require_weight boolean default false,
  require_bust boolean default false,
  require_waist boolean default false,
  limit_n integer default 20,
  offset_n integer default 0
)
returns table(
  id uuid,
  original_url_display text,
  product_page_url_display text,
  monetized_product_url_display text,
  brand text,
  source_site_display text,
  height_in_display numeric,
  weight_display_display text,
  size_display text,
  color_display text,
  bust_in_number_display integer,
  cupsize_display text,
  waist_in text,
  hips_in_display numeric,
  inseam_inches_display numeric,
  age_years_display integer,
  crop_spec jsonb,
  review_id uuid,
  product_page_id uuid,
  full_body_visible boolean,
  weeks_pregnant integer,
  prettiness_score double precision,
  mother_category_id text,
  -- total matches for these search params (same on every page); the window
  -- count runs over the full filtered set before LIMIT/OFFSET, so the frontend
  -- can show a true total instead of "loaded so far + ".
  total_count bigint
)
language sql
security definer
set search_path to 'pg_catalog', 'public', 'staging'
as $function$
  with scored as (
    select
      s.id,
      s.original_url_display,
      s.product_page_url_display,
      s.monetized_product_url_display,
      s.brand,
      s.source_site_display,
      s.height_in_display,
      s.weight_display_display,
      s.size_display,
      s.color_display,
      s.bust_in_number_display,
      s.cupsize_display,
      s.waist_in,
      s.hips_in_display,
      s.inseam_inches_display,
      s.age_years_display,
      s.crop_spec,
      s.review_id,
      s.product_page_id,
      s.full_body_visible,
      s.weeks_pregnant,
      s.prettiness_score,
      s.mother_category_id,
      (
        case
          when in_height is null then 0
          when s.height_in_display is null then 1.25
          else least(abs(s.height_in_display - in_height) / 2.0, 3.0)
        end
        +
        case
          when in_weight is null then 0
          when s.weight_lbs_display is null then 1.25
          else least(abs(s.weight_lbs_display - in_weight) / 10.0, 3.0)
        end
        +
        case
          when in_bust is null then 0
          when s.bust_in_number_display is null then 1.25
          else least(abs(s.bust_in_number_display - in_bust) / 2.0, 3.0)
        end
        +
        case
          when in_waist is null then 0
          when s.waist_in_numeric is null then 1.25
          else least(abs(s.waist_in_numeric - in_waist) / 2.0, 3.0)
        end
        +
        case
          when in_hips is null then 0
          when s.hips_in_display is null then 1.25
          else least(abs(s.hips_in_display - in_hips) / 2.0, 3.0)
        end
      ) as overall_closeness_score,
      (
        case when in_height is not null then 1 else 0 end
        + case when in_weight is not null then 1 else 0 end
        + case when in_bust is not null then 1 else 0 end
        + case when in_waist is not null then 1 else 0 end
        + case when in_hips is not null then 1 else 0 end
      ) as entered_measurement_count,
      s.created_at_display
    from public.searchable_images s
    where
      -- dead_link flagging stays live (cheap, indexed anti-join).
      not exists (
        select 1
        from public.image_reports ir
        where ir.image_id = s.id
          and ir.reason = 'dead_link'::public.image_report_reason
          and ir.anon_id = 'manual_product_category_review_2026_05_20'
      )
      -- in_clothing_type_id carries a mother_category_id value.
      and (in_clothing_type_id is null or s.mother_category_id = in_clothing_type_id)
      and (
        in_cup_size is null
        or (
          s.cupsize_display_normalized is not null
          and s.cupsize_display_normalized = upper(btrim(in_cup_size))
        )
      )
      and (
        not coalesce(require_height, false)
        or in_height is null
        or (s.height_in_display is not null and abs(s.height_in_display - in_height) <= 2)
      )
      and (
        not coalesce(require_weight, false)
        or in_weight is null
        or (s.weight_lbs_display is not null and abs(s.weight_lbs_display - in_weight) <= 10)
      )
      and (
        not coalesce(require_bust, false)
        or in_bust is null
        or (s.bust_in_number_display is not null and abs(s.bust_in_number_display - in_bust) <= 2)
      )
      and (
        not coalesce(require_waist, false)
        or in_waist is null
        or (s.waist_in_numeric is not null and abs(s.waist_in_numeric - in_waist) <= 2)
      )
      and (
        not coalesce(require_hips, false)
        or in_hips is null
        or (s.hips_in_display is not null and abs(s.hips_in_display - in_hips) <= 2)
      )
  )
  select
    s.id,
    s.original_url_display,
    s.product_page_url_display,
    s.monetized_product_url_display,
    s.brand,
    s.source_site_display,
    s.height_in_display,
    s.weight_display_display,
    s.size_display,
    s.color_display,
    s.bust_in_number_display,
    s.cupsize_display,
    s.waist_in,
    s.hips_in_display,
    s.inseam_inches_display,
    s.age_years_display,
    s.crop_spec,
    s.review_id,
    s.product_page_id,
    s.full_body_visible,
    s.weeks_pregnant,
    s.prettiness_score,
    s.mother_category_id,
    count(*) over() as total_count
  from scored s
  order by
    case
      when s.entered_measurement_count > 0 then s.overall_closeness_score / s.entered_measurement_count
      else 0
    end asc,
    s.created_at_display desc
  limit greatest(0, least(limit_n, 200))
  offset greatest(0, offset_n);
$function$;
