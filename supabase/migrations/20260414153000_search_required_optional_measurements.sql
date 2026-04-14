CREATE OR REPLACE FUNCTION public.match_by_measurements(
  in_clothing_type_id text DEFAULT NULL::text,
  in_height numeric DEFAULT NULL::numeric,
  in_hips numeric DEFAULT NULL::numeric,
  in_weight numeric DEFAULT NULL::numeric,
  in_bust numeric DEFAULT NULL::numeric,
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
  age_years_display integer
)
LANGUAGE sql
AS $function$
  with prepared as (
    select
      i.*,
      nullif(regexp_replace(coalesce(i.waist_in, ''), '[^0-9.]', '', 'g'), '')::numeric as waist_in_numeric
    from public.images i
    where
      i.original_url_display is not null
      and (i.size_display is not null and btrim(i.size_display) <> '' and lower(btrim(i.size_display)) <> 'unknown')
      and (i.monetized_product_url_display is not null or i.product_page_url_display is not null)
      and (
        i.height_in_display is not null
        or i.weight_lbs_display is not null
        or i.bust_in_number_display is not null
        or i.hips_in_display is not null
        or nullif(regexp_replace(coalesce(i.waist_in, ''), '[^0-9.]', '', 'g'), '') is not null
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
      (in_clothing_type_id is null or i.clothing_type_id = in_clothing_type_id)
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
    s.age_years_display
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

CREATE OR REPLACE FUNCTION public.match_by_measurements_deprecated(
  in_height numeric DEFAULT NULL::numeric,
  in_weight numeric DEFAULT NULL::numeric,
  in_bust numeric DEFAULT NULL::numeric,
  in_waist numeric DEFAULT NULL::numeric,
  in_hips numeric DEFAULT NULL::numeric,
  limit_n integer DEFAULT 24,
  offset_n integer DEFAULT 0
)
RETURNS TABLE(
  id uuid,
  original_url text,
  product_page_url text,
  monetized_product_url text,
  brand text,
  source_site text,
  height_in numeric,
  weight_lb numeric,
  size_ordered_raw text,
  color_ordered_raw text
)
LANGUAGE plpgsql
AS $function$
BEGIN
  RETURN QUERY
  SELECT
    m.id,
    m.original_url_display,
    m.product_page_url_display,
    m.monetized_product_url_display,
    m.brand,
    m.source_site_display,
    m.height_in_display,
    NULL::numeric,
    m.size_display,
    m.color_display
  FROM public.match_by_measurements(
    in_height => in_height,
    in_hips => in_hips,
    in_weight => in_weight,
    in_bust => in_bust,
    in_waist => in_waist,
    limit_n => limit_n,
    offset_n => offset_n
  ) AS m;
END;
$function$;

CREATE OR REPLACE FUNCTION public.match_by_measurements_deprecated(
  in_height numeric DEFAULT NULL::numeric,
  in_weight numeric DEFAULT NULL::numeric,
  in_bust numeric DEFAULT NULL::numeric,
  in_waist numeric DEFAULT NULL::numeric,
  in_hips numeric DEFAULT NULL::numeric,
  retailer text DEFAULT NULL::text,
  size_raw text DEFAULT NULL::text,
  color_raw text DEFAULT NULL::text,
  limit_n integer DEFAULT 48,
  offset_n integer DEFAULT 0
)
RETURNS TABLE(
  id uuid,
  original_url text,
  product_page_url text,
  monetized_product_url text,
  brand text,
  height_in numeric,
  weight_lb numeric,
  weight_display text,
  size_ordered_raw text,
  color_ordered_raw text,
  source_site text,
  created_at timestamp with time zone,
  score double precision
)
LANGUAGE plpgsql
AS $function$
BEGIN
  RETURN QUERY
  SELECT
    m.id,
    m.original_url_display,
    m.product_page_url_display,
    m.monetized_product_url_display,
    m.brand,
    m.height_in_display,
    NULL::numeric,
    m.weight_display_display,
    m.size_display,
    m.color_display,
    m.source_site_display,
    NULL::timestamp with time zone,
    NULL::double precision
  FROM public.match_by_measurements(
    in_height => in_height,
    in_hips => in_hips,
    in_weight => in_weight,
    in_bust => in_bust,
    in_waist => in_waist,
    limit_n => limit_n,
    offset_n => offset_n
  ) AS m;
END;
$function$;
