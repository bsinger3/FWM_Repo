-- Dev-only: add four sparse 'less common' filters to match_by_measurements.
--
-- inseam, bust-in-inches (bust_in_display, SEPARATE from the bra band), weeks
-- pregnant, and age have low coverage in public.images (1.5% / 2.1% / 0.5% /
-- 17.4%). They surface in a low-prominence collapsible section in index.dev.html;
-- when set they act as HARD filters (row must have the metric and be within
-- tolerance: inseam +-2in, bust +-2in, weeks +-4, age +-5), so results are
-- intentionally limited and the UI says so.
--
-- Built on dev_27 (low-res gate + dev_25 broad anti-join + total_count + dev_26
-- tiebreaker), all preserved verbatim. Changes vs dev_27:
--   * matview gains bust_in_display (filter-only; not in the return shape).
--   * function gains in_inseam / in_bust_inches / in_weeks_pregnant / in_age,
--     so the param list changes -> DROP the old 14-arg signature first.
-- Apply LAST. Any future full-function rebuild must carry every prior fix.
-- Idempotent: drop-if-exists + create-or-replace.

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
    i.bust_in_display,
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
  offset_n integer default 0,
  -- Sparse 'less common' filters (hard filters when provided).
  in_inseam numeric default null,
  in_bust_inches numeric default null,
  in_weeks_pregnant integer default null,
  in_age integer default null
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
      -- 'Less common' metrics: HARD filters (sparse coverage). When provided,
      -- the row must HAVE the metric and be within tolerance. This is why the
      -- UI warns matches are limited.
      and (in_inseam is null
        or (s.inseam_inches_display is not null and abs(s.inseam_inches_display - in_inseam) <= 2))
      and (in_bust_inches is null
        or (s.bust_in_display is not null and abs(s.bust_in_display - in_bust_inches) <= 2))
      and (in_weeks_pregnant is null
        or (s.weeks_pregnant is not null and abs(s.weeks_pregnant - in_weeks_pregnant) <= 4))
      and (in_age is null
        or (s.age_years_display is not null and abs(s.age_years_display - in_age) <= 5))
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
