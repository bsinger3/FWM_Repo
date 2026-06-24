-- Dev-only: make the high-level (mother) clothing category the canonical type
-- signal for search + display, sourced from staging.product_pages.
--
-- Why: public.images.clothing_type_id was extracted per-image and is unreliable.
-- The curated category lives on staging.product_pages (mother_category_id, backed
-- by confidence/evidence + manual review). The public frontend reads public.images
-- directly and cannot see the staging schema, so we denormalize the high-level
-- mother category onto public.images and expose a small public vocab table for the
-- search dropdown.
--
-- This migration:
--   1. Creates public.clothing_mother_categories (vocab for the dropdown).
--   2. Adds public.images.mother_category_id and backfills it from product_pages
--      (~100% of images have a product_page_id, so coverage is near-total).
--   3. Repoints match_by_measurements to filter on / return mother_category_id,
--      and makes it SECURITY DEFINER so its existing staging.product_pages
--      dead-page exclusion stops failing with "permission denied for schema
--      staging" for the anon role.
--
-- The legacy public.images.clothing_type_id column is intentionally LEFT IN PLACE
-- (now unused by the app) so this change stays reversible; drop it in a follow-up
-- once the high-level category is confirmed in the app.

-- 1. Public mother-category vocabulary. Mirrors staging.clothing_mother_categories
--    so the anon frontend can populate the category dropdown without touching the
--    staging schema. Read-only to anon, same grant pattern as public.clothing_types.
create table if not exists public.clothing_mother_categories (
  id text primary key,
  label text not null,
  sort_order integer not null default 999
);

insert into public.clothing_mother_categories (id, label, sort_order) values
  ('tops', 'Tops', 10),
  ('bottoms', 'Bottoms', 20),
  ('dresses', 'Dresses', 30),
  ('jumpsuit', 'Jumpsuit', 35),
  ('romper', 'Romper', 36),
  ('bodysuits', 'Bodysuits', 40),
  ('swimwear', 'Swimwear', 50),
  ('outerwear', 'Outerwear', 60),
  ('intimates', 'Intimates', 70),
  ('sets', 'Sets', 80),
  ('other', 'Other', 999)
on conflict (id) do update
  set label = excluded.label,
      sort_order = excluded.sort_order;

grant select on table public.clothing_mother_categories to anon;
grant select on table public.clothing_mother_categories to authenticated;
grant select on table public.clothing_mother_categories to service_role;

-- 2. Denormalize the high-level category onto images so type search/display is a
--    cheap single-table indexed read (and reachable by the anon frontend).
alter table public.images add column if not exists mother_category_id text;

update public.images i
   set mother_category_id = pp.mother_category_id
  from staging.product_pages pp
 where pp.id = i.product_page_id
   and i.mother_category_id is distinct from pp.mother_category_id;

create index if not exists images_mother_category_id_idx
  on public.images (mother_category_id);

-- 3. Repoint the search RPC to the mother category. The return type changes (adds
--    mother_category_id), so the function must be dropped and recreated rather than
--    CREATE OR REPLACE'd. The in_clothing_type_id parameter is kept (to avoid a
--    coordinated signature rename) but now carries a mother_category_id value.
--    SECURITY DEFINER lets the function read staging.product_pages for the
--    dead-page exclusion without granting anon access to the staging schema; the
--    search_path is pinned per SECURITY DEFINER best practice.
drop function if exists public.match_by_measurements(
  text, numeric, numeric, numeric, numeric, text, numeric, boolean, boolean,
  boolean, boolean, boolean, integer, integer
);

create function public.match_by_measurements(
  in_clothing_type_id text DEFAULT NULL::text,
  in_height numeric DEFAULT NULL::numeric,
  in_hips numeric DEFAULT NULL::numeric,
  in_weight numeric DEFAULT NULL::numeric,
  in_bust numeric DEFAULT NULL::numeric,
  in_cup_size text DEFAULT NULL::text,
  in_waist numeric DEFAULT NULL::numeric,
  require_height boolean DEFAULT false,
  require_hips boolean DEFAULT false,
  require_weight boolean DEFAULT false,
  require_bust boolean DEFAULT false,
  require_waist boolean DEFAULT false,
  limit_n integer DEFAULT 20,
  offset_n integer DEFAULT 0
)
RETURNS TABLE(
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
  mother_category_id text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public, staging
AS $function$
  with prepared as (
    select
      i.*,
      nullif(regexp_replace(coalesce(i.waist_in, ''), '[^0-9.]', '', 'g'), '')::numeric as waist_in_numeric,
      nullif(upper(btrim(i.cupsize_display)), '') as cupsize_display_normalized
    from public.images i
    where
      i.original_url_display is not null
      and not exists (
        select 1
        from public.image_reports ir
        where ir.image_id = i.id
          and ir.reason = 'dead_link'::public.image_report_reason
          and ir.anon_id = 'manual_product_category_review_2026_05_20'
      )
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
      )
  ),
  scored as (
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
      (
        case
          when in_height is null then 0
          when i.height_in_display is null then 1.25
          else least(abs(i.height_in_display - in_height) / 2.0, 3.0)
        end
        +
        case
          when in_weight is null then 0
          when i.weight_lbs_display is null then 1.25
          else least(abs(i.weight_lbs_display - in_weight) / 10.0, 3.0)
        end
        +
        case
          when in_bust is null then 0
          when i.bust_in_number_display is null then 1.25
          else least(abs(i.bust_in_number_display - in_bust) / 2.0, 3.0)
        end
        +
        case
          when in_waist is null then 0
          when i.waist_in_numeric is null then 1.25
          else least(abs(i.waist_in_numeric - in_waist) / 2.0, 3.0)
        end
        +
        case
          when in_hips is null then 0
          when i.hips_in_display is null then 1.25
          else least(abs(i.hips_in_display - in_hips) / 2.0, 3.0)
        end
      ) as overall_closeness_score,
      (
        case when in_height is not null then 1 else 0 end
        + case when in_weight is not null then 1 else 0 end
        + case when in_bust is not null then 1 else 0 end
        + case when in_waist is not null then 1 else 0 end
        + case when in_hips is not null then 1 else 0 end
      ) as entered_measurement_count,
      i.created_at_display
    from prepared i
    where
      -- in_clothing_type_id now carries a mother_category_id value.
      (in_clothing_type_id is null or i.mother_category_id = in_clothing_type_id)
      and (
        in_cup_size is null
        or (
          i.cupsize_display_normalized is not null
          and i.cupsize_display_normalized = upper(btrim(in_cup_size))
        )
      )
      and (
        not coalesce(require_height, false)
        or in_height is null
        or (
          i.height_in_display is not null
          and abs(i.height_in_display - in_height) <= 2
        )
      )
      and (
        not coalesce(require_weight, false)
        or in_weight is null
        or (
          i.weight_lbs_display is not null
          and abs(i.weight_lbs_display - in_weight) <= 10
        )
      )
      and (
        not coalesce(require_bust, false)
        or in_bust is null
        or (
          i.bust_in_number_display is not null
          and abs(i.bust_in_number_display - in_bust) <= 2
        )
      )
      and (
        not coalesce(require_waist, false)
        or in_waist is null
        or (
          i.waist_in_numeric is not null
          and abs(i.waist_in_numeric - in_waist) <= 2
        )
      )
      and (
        not coalesce(require_hips, false)
        or in_hips is null
        or (
          i.hips_in_display is not null
          and abs(i.hips_in_display - in_hips) <= 2
        )
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
    s.mother_category_id
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

GRANT EXECUTE ON FUNCTION public.match_by_measurements(
  text, numeric, numeric, numeric, numeric, text, numeric, boolean, boolean,
  boolean, boolean, boolean, integer, integer
) TO anon;
GRANT EXECUTE ON FUNCTION public.match_by_measurements(
  text, numeric, numeric, numeric, numeric, text, numeric, boolean, boolean,
  boolean, boolean, boolean, integer, integer
) TO authenticated;
GRANT EXECUTE ON FUNCTION public.match_by_measurements(
  text, numeric, numeric, numeric, numeric, text, numeric, boolean, boolean,
  boolean, boolean, boolean, integer, integer
) TO service_role;
