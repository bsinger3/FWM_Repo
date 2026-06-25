-- Dev-only: POLICY — any flagged image is hidden from ALL searches (never deleted).
--
-- Before: match_by_measurements excluded only ONE narrow report class —
--   reason='dead_link' AND anon_id='manual_product_category_review_2026_05_20'
--   (the 2026-05-20 manual dead-link sweep).
--
-- Now: if ANYONE — the operator or any anonymous user — files ANY report against
-- an image (any reason: image_not_helpful, dead_link, duplicate_image, ...), that
-- image disappears from every search result immediately. The row stays in
-- public.images; only its visibility in match_by_measurements changes.
--
-- Implementation: broaden the existing LIVE anti-join from the specific
-- (reason, anon_id) pair to "any row in public.image_reports for this image".
--   * LIVE (in the function, not baked into searchable_images) → a flag hides the
--     image on the very next search with no materialized-view refresh.
--   * Cheap → backed by idx_image_reports_image_id on image_reports(image_id).
--   * The dead_link sweep is a subset of "any report", so nothing it hid resurfaces.
--
-- This is a verbatim copy of the LIVE dev function (which adds total_count bigint
-- on top of dev_24) with ONLY the anti-join broadened. CREATE OR REPLACE cannot
-- change a function's return type, so the full RETURNS TABLE — including
-- total_count — must be reproduced exactly or the replace silently no-ops.
--
-- Dev-migrations/ is applied to dev only; production's function is untouched.
-- Idempotent: CREATE OR REPLACE. Re-running is safe.

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
