-- Dev-only: hide low-resolution images from search, server-side.
--
-- Problem: many source photos are small (~600px or less). The garment-aware
-- auto-crop (crop_spec mode 'cover-window') zooms into a sub-window and the
-- frontend upscales it to fill the card, so a low-res source looks pixelated.
-- index.dev.html already hides these client-side at image-load time
-- (thumbSharpnessRatio / hideCardIfLowRes, MIN_THUMB_SHARPNESS = 0.9) — but that
-- is per-load and does NOT reduce what match_by_measurements returns, so paging
-- and counts are polluted by cards the user never sees.
--
-- Fix (mirrors the client formula on the server):
--   1. 20260625_dev_26 added numeric source_width_px / source_height_px to
--      public.images; backfill-dev-image-dimensions.mjs populated them.
--   2. This migration rebuilds public.searchable_images to also precompute
--      min_thumb_sharpness — the same ratio the client computes, evaluated at a
--      fixed reference (a 180x240 CSS-px card at devicePixelRatio 2 = 360x480
--      device px):
--          haveW = source_width_px  * windowWPct/100
--          haveH = source_height_px * windowHPct/100
--          min_thumb_sharpness = min( haveW/(360*scale), haveH/(480*scale) )
--      ratio >= 1 means the source has enough pixels (crisp); ratio < 1 means it
--      gets upscaled (soft/pixelated). For non-window crops, windowWPct/HPct are
--      100 and scale follows the crop zoom; for images with unknown source dims
--      the metric is NULL (treated as "don't hide", same as the client returning
--      Infinity when naturalWidth is unknown).
--   3. match_by_measurements gains one anti-low-res predicate. The threshold is a
--      single SQL literal (LOW_RES_MIN_SHARPNESS = 0.9, matching the client) kept
--      LIVE in the function body so it can be retuned by re-applying this file
--      WITHOUT a materialized-view refresh.
--
-- This preserves the LIVE dev shape verbatim: the matview is dev_24 plus the new
-- column; the function is dev_25 (the broad image_reports anti-join — ANY report
-- hides the image — plus total_count) AND the dev_26 pagination tiebreaker
-- (`, s.id` in ORDER BY), with the low-res predicate added on top. (Because this
-- file rebuilds the whole function, it MUST carry every prior fix or it regresses
-- them — apply dev_27 last.)
-- CREATE OR REPLACE cannot change a function's return type, so the full RETURNS
-- TABLE (incl. total_count) is reproduced exactly. SQL function bodies here use
-- the quoted ($function$) form, which is not dependency-tracked, so dropping and
-- recreating the matview underneath the function is safe.
--
-- Dev-migrations/ is applied to dev only; production's function is untouched.
-- Idempotent: drop-if-exists + create-or-replace. Re-running is safe.

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
    nullif(upper(btrim(i.cupsize_display)), '') as cupsize_display_normalized,
    -- precomputed server-side sharpness, mirroring index.dev.html thumbSharpnessRatio().
    -- NULL when source dimensions are unknown (do-not-hide), matching the client.
    g.min_thumb_sharpness
  from public.images i
  cross join lateral (
    select
      case
        when i.source_width_px is null or i.source_height_px is null
             or i.source_width_px <= 0 or i.source_height_px <= 0 then null
        else least(
          (i.source_width_px  * win.ww / 100.0) / (360.0 * win.scale),
          (i.source_height_px * win.wh / 100.0) / (480.0 * win.scale)
        )
      end as min_thumb_sharpness
    from (
      select
        -- windowWPct/HPct only apply to the 'cover-window' crop; otherwise 100%.
        case
          when i.crop_spec->>'mode' = 'cover-window'
               and jsonb_typeof(i.crop_spec->'windowWPct') = 'number'
               and (i.crop_spec->>'windowWPct')::numeric > 0
          then (i.crop_spec->>'windowWPct')::numeric else 100
        end as ww,
        case
          when i.crop_spec->>'mode' = 'cover-window'
               and jsonb_typeof(i.crop_spec->'windowHPct') = 'number'
               and (i.crop_spec->>'windowHPct')::numeric > 0
          then (i.crop_spec->>'windowHPct')::numeric else 100
        end as wh,
        -- non-window crops scale by zoom (capped at 1.6, as the client does).
        case
          when i.crop_spec->>'mode' = 'cover-window' then 1.0
          when jsonb_typeof(i.crop_spec->'zoom') = 'number'
               and (i.crop_spec->>'zoom')::numeric > 1
          then least(1.6, (i.crop_spec->>'zoom')::numeric)
          else 1.0
        end as scale
    ) win
  ) g
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

-- Return type is unchanged from dev_25, so CREATE OR REPLACE suffices.
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
      -- POLICY: ANY report from ANYONE (operator or user, any reason) hides the
      -- image from all searches. Live, indexed anti-join — immediate on flag,
      -- no materialized-view refresh, and the image is never deleted.
      not exists (
        select 1
        from public.image_reports ir
        where ir.image_id = s.id
      )
      -- LOW-RES GATE: drop images whose source can't fill the thumb crisply.
      -- LOW_RES_MIN_SHARPNESS = 0.9 (matches index.dev.html MIN_THUMB_SHARPNESS).
      -- NULL sharpness (unknown source dims) is treated as "keep", mirroring the
      -- client returning Infinity. Tune by editing the 0.9 below and re-applying
      -- this migration — no matview refresh needed (the metric is precomputed,
      -- only the comparison is live).
      and coalesce(s.min_thumb_sharpness, 1e9) >= 0.9
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
    s.created_at_display desc,
    -- Unique tiebreaker (from 20260625_dev_26_search_pagination_tiebreaker): without
    -- it many rows tie on (score, created_at) and OFFSET paging is non-deterministic,
    -- so the same row can appear on two pages (duplicate cards on scroll). Preserved
    -- here because this migration rebuilds the whole function and must not regress it.
    s.id
  limit greatest(0, least(limit_n, 200))
  offset greatest(0, offset_n);
$function$;
