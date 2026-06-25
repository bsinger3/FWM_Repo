-- Dev-only: tighten the 'matches' tolerances used for the header match count.
--
-- matches_any (which drives match_count and the matches-first sort in dev_29)
-- now requires a closer fit: height/bust/waist/hips +-1.5in (was +-2), weight
-- +-7lb (was +-10). Same signature + return shape as dev_29, so this is a plain
-- CREATE OR REPLACE (no drop). The require-* hard filters keep their own
-- tolerances (unchanged). Apply LAST; supersedes dev_29's function body.

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
  total_count bigint,
  -- true if the row is within tolerance of >=1 entered measurement
  matches_any boolean,
  -- count of rows that match >=1 entered measurement (the header number)
  match_count bigint
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
      s.created_at_display,
      (
        (in_height is not null and s.height_in_display is not null and abs(s.height_in_display - in_height) <= 1.5)
        or (in_weight is not null and s.weight_lbs_display is not null and abs(s.weight_lbs_display - in_weight) <= 7)
        or (in_bust is not null and s.bust_in_number_display is not null and abs(s.bust_in_number_display - in_bust) <= 1.5)
        or (in_waist is not null and s.waist_in_numeric is not null and abs(s.waist_in_numeric - in_waist) <= 1.5)
        or (in_hips is not null and s.hips_in_display is not null and abs(s.hips_in_display - in_hips) <= 1.5)
      ) as matches_any
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
    count(*) over() as total_count,
    s.matches_any,
    count(*) filter (where s.matches_any) over() as match_count
  from scored s
  order by
    -- Within-tolerance matches first (the top 'results' count), then the
    -- ranked 'close matches' remainder. Both groups stay best-first.
    s.matches_any desc,
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
