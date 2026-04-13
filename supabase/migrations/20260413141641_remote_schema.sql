create extension if not exists "vector" with schema "extensions";

drop extension if exists "pg_net";

create schema if not exists "archive";

create schema if not exists "archive_images";

create extension if not exists "pg_trgm" with schema "public";


  create table "archive"."color_map" (
    "raw" text not null,
    "norm" text
      );



  create table "archive"."image_vectors" (
    "image_id" uuid not null,
    "embedding" extensions.vector(768),
    "model_name" text,
    "updated_at" timestamp with time zone default now()
      );



  create table "archive"."images_backup" (
    "id" uuid,
    "original_url" text,
    "product_page_url" text,
    "monetized_product_url" text,
    "height_raw" text,
    "weight_raw" text,
    "size_ordered_raw" text,
    "color_ordered_raw" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in" numeric,
    "weight_lb" numeric,
    "size_ordered_norm" text,
    "color_norm" text,
    "review_date" date,
    "source_site" text,
    "status_code" integer,
    "content_type" text,
    "bytes" bigint,
    "width" integer,
    "height" integer,
    "hash_md5" text,
    "fetched_at" timestamp with time zone,
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "brand" text,
    "bust_raw" text,
    "waist_raw" text,
    "hips_raw" text,
    "age_raw" text,
    "bust_in" numeric,
    "waist_in" numeric,
    "hips_in" numeric,
    "age_years" integer,
    "search_fts" tsvector,
    "weight_display" text,
    "weight_raw_needs_correction" integer
      );



  create table "archive"."images_backup_20260126_212348" (
    "created_at_display" timestamp with time zone,
    "id" uuid,
    "original_url_display" text,
    "product_page_url_display" text,
    "monetized_product_url_display" text,
    "height_raw" text,
    "weight_raw" text,
    "size_ordered_raw_display" text,
    "color_ordered_raw_display" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in_display" numeric,
    "weight_lb" text,
    "size_ordered_norm" text,
    "color_norm" text,
    "review_date" text,
    "source_site_display" text,
    "status_code" text,
    "content_type" text,
    "bytes" text,
    "width" text,
    "height" text,
    "hash_md5" text,
    "fetched_at" text,
    "updated_at" text,
    "brand" text,
    "bust_raw" text,
    "waist_raw_display" text,
    "hips_raw" text,
    "age_raw" text,
    "bust_in_display" text,
    "waist_in" text,
    "hips_in_display" numeric,
    "age_years_display" integer,
    "search_fts" text,
    "weight_display_display" text,
    "weight_raw_needs_correction" text
      );



  create table "archive"."images_deprecated_2025_12_30" (
    "id" uuid not null default gen_random_uuid(),
    "original_url" text not null,
    "product_page_url" text,
    "monetized_product_url" text,
    "height_raw" text,
    "weight_raw" text,
    "size_ordered_raw" text,
    "color_ordered_raw" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in" numeric,
    "weight_lb" numeric,
    "size_ordered_norm" text,
    "color_norm" text,
    "review_date" date,
    "source_site" text,
    "status_code" integer,
    "content_type" text,
    "bytes" bigint,
    "width" integer,
    "height" integer,
    "hash_md5" text,
    "fetched_at" timestamp with time zone,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now(),
    "brand" text,
    "bust_raw" text,
    "waist_raw" text,
    "hips_raw" text,
    "age_raw" text,
    "bust_in" numeric,
    "waist_in" numeric,
    "hips_in" numeric,
    "age_years" integer,
    "search_fts" tsvector generated always as (to_tsvector('english'::regconfig, ((((((((((COALESCE(brand, ''::text) || ' '::text) || COALESCE(size_ordered_raw, ''::text)) || ' '::text) || COALESCE(color_ordered_raw, ''::text)) || ' '::text) || COALESCE(source_site, ''::text)) || ' '::text) || regexp_replace(COALESCE(product_page_url, ''::text), '[^a-zA-Z0-9]+'::text, ' '::text, 'g'::text)) || ' '::text) || regexp_replace(COALESCE(original_url, ''::text), '[^a-zA-Z0-9]+'::text, ' '::text, 'g'::text)))) stored,
    "weight_display" text,
    "weight_raw_needs_correction" integer default 0
      );



  create table "archive"."images_import_dec2025_2" (
    "created_at" timestamp with time zone not null default now(),
    "id" uuid not null default gen_random_uuid(),
    "original_url" text,
    "product_page_url" text,
    "monetized_product_url" text,
    "height_raw" text,
    "weight_raw" text,
    "size_ordered_raw" text,
    "color_ordered_raw" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in" numeric,
    "weight_lb" text,
    "size_ordered_norm" text,
    "color_norm" text,
    "review_date" text,
    "source_site" text,
    "status_code" text,
    "content_type" text,
    "bytes" text,
    "width" text,
    "height" text,
    "hash_md5" text,
    "fetched_at" text,
    "updated_at" text default now(),
    "brand" text,
    "bust_raw" text,
    "waist_raw" text,
    "hips_raw" text,
    "age_raw" text,
    "bust_in" text,
    "waist_in" text,
    "hips_in" numeric,
    "age_years" integer,
    "search_fts" text,
    "weight_display" text,
    "weight_raw_needs_correction" text default 0
      );



  create table "archive"."raw_fwm_import" (
    "BigImage" text not null,
    "ProdPage_NotMonetized" text,
    "VigLink" text,
    "Brand" text,
    "SizePurchased" text,
    "Bust" text,
    "Weight" text,
    "Height" text,
    "Age" text,
    "Waist" text,
    "Hips" text
      );


alter table "archive"."raw_fwm_import" enable row level security;


  create table "archive"."size_map" (
    "raw" text not null,
    "norm" text
      );



  create table "archive_images"."images_backup_20260320" (
    "created_at_display" timestamp with time zone,
    "id" uuid not null,
    "original_url_display" text,
    "product_page_url_display" text,
    "monetized_product_url_display" text,
    "height_raw" text,
    "weight_raw" text,
    "size_ordered_raw_display" text,
    "color_ordered_raw_display" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in_display" numeric,
    "weight_lb" text,
    "size_ordered_norm" text,
    "color_norm" text,
    "review_date" text,
    "source_site_display" text,
    "status_code" text,
    "content_type" text,
    "bytes" text,
    "width" text,
    "height" text,
    "hash_md5" text,
    "fetched_at" text,
    "updated_at" text,
    "brand" text,
    "bust_raw" text,
    "waist_raw_display" text,
    "hips_raw" text,
    "age_raw" text,
    "bust_in_display" text,
    "waist_in" text,
    "hips_in_display" numeric,
    "age_years_display" integer,
    "search_fts" text,
    "weight_display_display" text,
    "weight_raw_needs_correction" text,
    "clothing_type_id" text,
    "reviewer_profile_url" text,
    "reviewer_name_raw" text,
    "inseam_inches_display" numeric
      );



  create table "public"."archive.images_backup_20260320_063904" (
    "created_at_display" timestamp with time zone,
    "id" uuid,
    "original_url_display" text,
    "product_page_url_display" text,
    "monetized_product_url_display" text,
    "height_raw" text,
    "weight_raw" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in_display" numeric,
    "weight_lb" text,
    "review_date" text,
    "source_site_display" text,
    "status_code" text,
    "content_type" text,
    "bytes" text,
    "width" text,
    "height" text,
    "hash_md5" text,
    "fetched_at" text,
    "updated_at" text,
    "brand" text,
    "waist_raw_display" text,
    "hips_raw" text,
    "age_raw" text,
    "waist_in" text,
    "hips_in_display" numeric,
    "age_years_display" integer,
    "search_fts" text,
    "weight_display_display" text,
    "weight_raw_needs_correction" text,
    "clothing_type_id" text,
    "reviewer_profile_url" text,
    "reviewer_name_raw" text,
    "inseam_inches_display" numeric,
    "color_canonical" text,
    "color_display" text,
    "size_display" text,
    "bust_in_number_display" integer,
    "cupsize_display" text,
    "weight_lbs_display" numeric,
    "weight_lbs_raw_issue" text
      );



  create table "public"."clothing_types" (
    "id" text not null,
    "label" text not null,
    "sort_order" integer not null default 999
      );



  create table "public"."images" (
    "created_at_display" timestamp with time zone not null default now(),
    "id" uuid not null,
    "original_url_display" text,
    "product_page_url_display" text,
    "monetized_product_url_display" text,
    "height_raw" text,
    "weight_raw" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in_display" numeric,
    "weight_lb" text,
    "review_date" text,
    "source_site_display" text,
    "status_code" text,
    "content_type" text,
    "bytes" text,
    "width" text,
    "height" text,
    "hash_md5" text,
    "fetched_at" text,
    "updated_at" text,
    "brand" text,
    "waist_raw_display" text,
    "hips_raw" text,
    "age_raw" text,
    "waist_in" text,
    "hips_in_display" numeric,
    "age_years_display" integer,
    "search_fts" text,
    "weight_display_display" text,
    "weight_raw_needs_correction" text,
    "clothing_type_id" text,
    "reviewer_profile_url" text,
    "reviewer_name_raw" text,
    "inseam_inches_display" numeric,
    "color_canonical" text,
    "color_display" text,
    "size_display" text not null,
    "bust_in_number_display" integer,
    "cupsize_display" text,
    "weight_lbs_display" numeric,
    "weight_lbs_raw_issue" text
      );



  create table "public"."images_backup_20260320" (
    "created_at_display" timestamp with time zone,
    "id" uuid,
    "original_url_display" text,
    "product_page_url_display" text,
    "monetized_product_url_display" text,
    "height_raw" text,
    "weight_raw" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in_display" numeric,
    "weight_lb" text,
    "review_date" text,
    "source_site_display" text,
    "status_code" text,
    "content_type" text,
    "bytes" text,
    "width" text,
    "height" text,
    "hash_md5" text,
    "fetched_at" text,
    "updated_at" text,
    "brand" text,
    "waist_raw_display" text,
    "hips_raw" text,
    "age_raw" text,
    "waist_in" text,
    "hips_in_display" numeric,
    "age_years_display" integer,
    "search_fts" text,
    "weight_display_display" text,
    "weight_raw_needs_correction" text,
    "clothing_type_id" text,
    "reviewer_profile_url" text,
    "reviewer_name_raw" text,
    "inseam_inches_display" numeric,
    "color_canonical" text,
    "color_display" text,
    "size_display" text,
    "bust_in_number_display" integer,
    "cupsize_display" text,
    "weight_lbs_display" numeric,
    "weight_lbs_raw_issue" text
      );



  create table "public"."images_staging" (
    "created_at_display" timestamp with time zone,
    "id" uuid,
    "original_url_display" text,
    "product_page_url_display" text,
    "monetized_product_url_display" text,
    "height_raw" text,
    "weight_raw" text,
    "user_comment" text,
    "date_review_submitted_raw" text,
    "height_in_display" numeric,
    "weight_lb" text,
    "review_date" text,
    "source_site_display" text,
    "status_code" text,
    "content_type" text,
    "bytes" text,
    "width" text,
    "height" text,
    "hash_md5" text,
    "fetched_at" text,
    "updated_at" text,
    "brand" text,
    "waist_raw_display" text,
    "hips_raw" text,
    "age_raw" text,
    "waist_in" text,
    "hips_in_display" numeric,
    "age_years_display" integer,
    "search_fts" text,
    "weight_display_display" text,
    "weight_raw_needs_correction" text,
    "clothing_type_id" text,
    "reviewer_profile_url" text,
    "reviewer_name_raw" text,
    "inseam_inches_display" numeric,
    "color_canonical" text,
    "color_display" text,
    "size_display" text,
    "bust_in_number_display" integer,
    "cupsize_display" text,
    "weight_lbs_display" numeric,
    "weight_lbs_raw_issue" text
      );



  create table "public"."search_events" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamp with time zone not null default now(),
    "anon_id" text not null,
    "session_id" text not null,
    "page_url" text,
    "referrer" text,
    "utm_source" text,
    "utm_medium" text,
    "utm_campaign" text,
    "utm_content" text,
    "feet" integer,
    "inches" integer,
    "weight_lb" integer,
    "bust_in" integer,
    "hips_in" integer,
    "clothing_type" text,
    "results_count" integer,
    "latency_ms" integer
      );


alter table "public"."search_events" enable row level security;

CREATE UNIQUE INDEX color_map_pkey ON archive.color_map USING btree (raw);

CREATE INDEX idx_images_bust ON archive.images_deprecated_2025_12_30 USING btree (bust_in);

CREATE INDEX idx_images_filters ON archive.images_deprecated_2025_12_30 USING btree (color_norm, size_ordered_norm, review_date);

CREATE INDEX idx_images_fts ON archive.images_deprecated_2025_12_30 USING gin (to_tsvector('english'::regconfig, ((((COALESCE(user_comment, ''::text) || ' '::text) || COALESCE(size_ordered_raw, ''::text)) || ' '::text) || COALESCE(color_ordered_raw, ''::text))));

CREATE INDEX idx_images_height ON archive.images_deprecated_2025_12_30 USING btree (height_in);

CREATE INDEX idx_images_hips ON archive.images_deprecated_2025_12_30 USING btree (hips_in);

CREATE INDEX idx_images_search_fts ON archive.images_deprecated_2025_12_30 USING gin (search_fts);

CREATE INDEX idx_images_source ON archive.images_deprecated_2025_12_30 USING btree (lower(source_site));

CREATE INDEX idx_images_waist ON archive.images_deprecated_2025_12_30 USING btree (waist_in);

CREATE INDEX idx_images_weight ON archive.images_deprecated_2025_12_30 USING btree (weight_lb);

CREATE UNIQUE INDEX image_vectors_pkey ON archive.image_vectors USING btree (image_id);

CREATE UNIQUE INDEX images_import_image_uuid_key ON archive.images_import_dec2025_2 USING btree (id);

CREATE UNIQUE INDEX images_import_pkey ON archive.images_import_dec2025_2 USING btree (id);

CREATE UNIQUE INDEX images_pkey ON archive.images_deprecated_2025_12_30 USING btree (id);

CREATE UNIQUE INDEX raw_fwm_import_pkey ON archive.raw_fwm_import USING btree ("BigImage");

CREATE UNIQUE INDEX size_map_pkey ON archive.size_map USING btree (raw);

CREATE UNIQUE INDEX images_backup_20260320_pkey ON archive_images.images_backup_20260320 USING btree (id);

CREATE UNIQUE INDEX clothing_types_pkey ON public.clothing_types USING btree (id);

CREATE INDEX idx_images_weight_lbs_display ON public.images USING btree (weight_lbs_display);

CREATE INDEX images_brand_idx ON public.images USING btree (brand);

CREATE INDEX images_clothing_type_id_idx ON public.images USING btree (clothing_type_id);

CREATE INDEX images_created_at_display_idx ON public.images USING btree (created_at_display DESC);

CREATE INDEX images_hash_md5_idx ON public.images USING btree (hash_md5);

CREATE UNIQUE INDEX images_hash_md5_uniq ON public.images USING btree (hash_md5) WHERE ((hash_md5 IS NOT NULL) AND (btrim(hash_md5) <> ''::text));

CREATE UNIQUE INDEX images_pkey ON public.images USING btree (id);

CREATE INDEX images_search_fts_trgm ON public.images USING gin (search_fts public.gin_trgm_ops);

CREATE UNIQUE INDEX search_events_pkey ON public.search_events USING btree (id);

alter table "archive"."color_map" add constraint "color_map_pkey" PRIMARY KEY using index "color_map_pkey";

alter table "archive"."image_vectors" add constraint "image_vectors_pkey" PRIMARY KEY using index "image_vectors_pkey";

alter table "archive"."images_deprecated_2025_12_30" add constraint "images_pkey" PRIMARY KEY using index "images_pkey";

alter table "archive"."images_import_dec2025_2" add constraint "images_import_pkey" PRIMARY KEY using index "images_import_pkey";

alter table "archive"."raw_fwm_import" add constraint "raw_fwm_import_pkey" PRIMARY KEY using index "raw_fwm_import_pkey";

alter table "archive"."size_map" add constraint "size_map_pkey" PRIMARY KEY using index "size_map_pkey";

alter table "archive_images"."images_backup_20260320" add constraint "images_backup_20260320_pkey" PRIMARY KEY using index "images_backup_20260320_pkey";

alter table "public"."clothing_types" add constraint "clothing_types_pkey" PRIMARY KEY using index "clothing_types_pkey";

alter table "public"."images" add constraint "images_pkey" PRIMARY KEY using index "images_pkey";

alter table "public"."search_events" add constraint "search_events_pkey" PRIMARY KEY using index "search_events_pkey";

alter table "archive"."image_vectors" add constraint "image_vectors_image_id_fkey" FOREIGN KEY (image_id) REFERENCES archive.images_deprecated_2025_12_30(id) ON DELETE CASCADE not valid;

alter table "archive"."image_vectors" validate constraint "image_vectors_image_id_fkey";

alter table "archive"."images_import_dec2025_2" add constraint "images_import_image_uuid_key" UNIQUE using index "images_import_image_uuid_key";

alter table "archive_images"."images_backup_20260320" add constraint "images_backup_clothing_type_fk" FOREIGN KEY (clothing_type_id) REFERENCES public.clothing_types(id) not valid;

alter table "archive_images"."images_backup_20260320" validate constraint "images_backup_clothing_type_fk";

alter table "public"."images" add constraint "images_clothing_type_fk" FOREIGN KEY (clothing_type_id) REFERENCES public.clothing_types(id) not valid;

alter table "public"."images" validate constraint "images_clothing_type_fk";

alter table "public"."images" add constraint "images_must_have_some_product_url" CHECK ((((product_page_url_display IS NOT NULL) AND (length(btrim(product_page_url_display)) > 0)) OR ((monetized_product_url_display IS NOT NULL) AND (length(btrim(monetized_product_url_display)) > 0)))) not valid;

alter table "public"."images" validate constraint "images_must_have_some_product_url";

alter table "public"."images" add constraint "images_original_url_display_not_blank" CHECK (((original_url_display IS NOT NULL) AND (length(btrim(original_url_display)) > 0))) not valid;

alter table "public"."images" validate constraint "images_original_url_display_not_blank";

set check_function_bodies = off;

create or replace view "archive"."images_public" as  SELECT id,
    original_url,
    product_page_url,
    monetized_product_url,
    brand,
    height_in,
    weight_lb,
    size_ordered_raw,
    color_ordered_raw,
    review_date,
    source_site,
    created_at
   FROM archive.images_deprecated_2025_12_30;


CREATE OR REPLACE FUNCTION public.format_weight_display(p_weight_lb numeric, p_weight_raw text)
 RETURNS text
 LANGUAGE sql
 STABLE
AS $function$
WITH raw AS (
  SELECT COALESCE(p_weight_raw, '') AS raw_text,
         p_weight_lb AS weight_lb
)
SELECT
  CASE
    -- If numeric weight present, prefer a simple normalized numeric representation
    WHEN weight_lb IS NOT NULL THEN trim(regexp_replace(weight_lb::text, '\.0+$', ''))
    ELSE
      -- Otherwise parse raw text
      (
        WITH w AS (
          SELECT raw_text AS raw,
                 regexp_replace(raw_text, '[^0-9]', '', 'g') AS digits
        )
        SELECT
          COALESCE(
            -- concatenated 6-digit like 130140 -> '130 - 140'
            (CASE WHEN digits ~ '^[0-9]{6}$' THEN substring(digits from 1 for 3) || ' - ' || substring(digits from 4 for 3) ELSE NULL END),
            -- explicit separators like '130-140' or '130 / 140' -> normalize to '130 - 140'
            (CASE WHEN regexp_replace(raw, '\s*[-/]\s*', ' - ', 'g') ~ '^\s*[0-9]+\s*-\s*[0-9]+\s*$' THEN regexp_replace(raw, '\s*[-/]\s*', ' - ', 'g') ELSE NULL END),
            -- single numeric string -> trimmed
            (CASE WHEN trim(raw) ~ '^[0-9]+$' THEN trim(raw) ELSE NULL END),
            -- fallback to trimmed original
            trim(raw)
          )
        FROM w
      )
  END
FROM raw;
$function$
;

CREATE OR REPLACE FUNCTION public.host_name(u text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select split_part(nullif(u,''),'/',3);
$function$
;

CREATE OR REPLACE FUNCTION public.inspect_table_columns_examples(in_schema text, in_table text, example_limit integer DEFAULT 5)
 RETURNS TABLE(column_name text, data_type text, is_nullable text, character_maximum_length integer, examples text[], distinct_count bigint, min_value text, max_value text)
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  col_rec RECORD;
  sql text;
  examples_arr text[];
  distinct_cnt bigint;
  min_val text;
  max_val text;
BEGIN
  FOR col_rec IN
    SELECT c.column_name, c.data_type, c.is_nullable, c.character_maximum_length
    FROM information_schema.columns c
    WHERE c.table_schema = in_schema
      AND c.table_name = in_table
    ORDER BY c.ordinal_position
  LOOP
    sql := format($f$
      WITH vals AS (
        SELECT (%s)::text AS v
        FROM %I.%I
        WHERE %s IS NOT NULL
      )
      SELECT
        (SELECT array_agg(DISTINCT v ORDER BY v LIMIT %s) FROM vals) AS examples,
        (SELECT count(DISTINCT v) FROM vals) AS distinct_cnt,
        (SELECT min(v) FROM vals) AS min_v,
        (SELECT max(v) FROM vals) AS max_v
      ;
    $f$,
      format('%I', col_rec.column_name),
      in_schema, in_table,
      format('%I', col_rec.column_name),
      example_limit
    );

    EXECUTE sql INTO examples_arr, distinct_cnt, min_val, max_val;

    column_name := col_rec.column_name;
    data_type := col_rec.data_type;
    is_nullable := col_rec.is_nullable;
    character_maximum_length := col_rec.character_maximum_length;
    examples := examples_arr;
    distinct_count := coalesce(distinct_cnt, 0);
    min_value := min_val;
    max_value := max_val;
    RETURN NEXT;
  END LOOP;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.match_by_measurements(in_clothing_type_id text DEFAULT NULL::text, in_height numeric DEFAULT NULL::numeric, in_hips numeric DEFAULT NULL::numeric, in_weight numeric DEFAULT NULL::numeric, in_bust numeric DEFAULT NULL::numeric, limit_n integer DEFAULT 20, offset_n integer DEFAULT 0)
 RETURNS TABLE(id uuid, original_url_display text, product_page_url_display text, monetized_product_url_display text, brand text, source_site_display text, height_in_display numeric, weight_display_display text, size_display text, color_display text, bust_in_number_display integer)
 LANGUAGE sql
AS $function$
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
    i.bust_in_number_display
  from public.images i
  where
    i.original_url_display is not null
    and (i.size_display is not null and btrim(i.size_display) <> '')
    and (
      i.height_in_display is not null
      or (i.weight_display_display is not null and btrim(i.weight_display_display) <> '')
      or (i.bust_in_number_display is not null)
    )
    and (
      /* No match inputs: keep old behavior (candidates). */
      (in_clothing_type_id is null
       and in_height is null
       and in_hips is null
       and in_weight is null
       and in_bust is null)

      or (
        /* If client provided a clothing type, ALWAYS require it. */
        (in_clothing_type_id is null or i.clothing_type_id = in_clothing_type_id)

        and (
          /* If the client provided no measurement inputs, accept the clothing type alone. */
          (in_height is null and in_hips is null and in_weight is null and in_bust is null)

          or (
            /* Otherwise, match ANY provided measurement dimension. */
            (in_height is not null and i.height_in_display is not null and abs(i.height_in_display - in_height) <= 2)
            or (in_hips is not null and i.hips_in_display is not null and abs(i.hips_in_display - in_hips) <= 2)
            or (
              in_weight is not null and
              i.weight_display_display is not null and
              btrim(i.weight_display_display) <> '' and
              nullif(regexp_replace(i.weight_display_display, '[^0-9.]', '', 'g'), '') is not null and
              abs(
                (nullif(regexp_replace(i.weight_display_display, '[^0-9.]', '', 'g'), '')::numeric) - in_weight
              ) <= 10
            )
            or (in_bust is not null and i.bust_in_number_display is not null and abs(i.bust_in_number_display - in_bust) <= 2)
          )
        )
      )
    )
  order by i.created_at_display desc
  limit greatest(0, least(limit_n, 200))
  offset greatest(0, offset_n);
$function$
;

CREATE OR REPLACE FUNCTION public.match_by_measurements_deprecated(in_height numeric DEFAULT NULL::numeric, in_weight numeric DEFAULT NULL::numeric, in_bust numeric DEFAULT NULL::numeric, in_waist numeric DEFAULT NULL::numeric, in_hips numeric DEFAULT NULL::numeric, limit_n integer DEFAULT 24, offset_n integer DEFAULT 0)
 RETURNS TABLE(id uuid, original_url text, product_page_url text, monetized_product_url text, brand text, source_site text, height_in numeric, weight_lb numeric, size_ordered_raw text, color_ordered_raw text)
 LANGUAGE plpgsql
AS $function$
BEGIN
  RETURN QUERY
  SELECT * FROM public.match_by_measurements(in_height, in_weight, in_bust, in_waist, in_hips, limit_n, offset_n);
END;
$function$
;

CREATE OR REPLACE FUNCTION public.match_by_measurements_deprecated(in_height numeric DEFAULT NULL::numeric, in_weight numeric DEFAULT NULL::numeric, in_bust numeric DEFAULT NULL::numeric, in_waist numeric DEFAULT NULL::numeric, in_hips numeric DEFAULT NULL::numeric, retailer text DEFAULT NULL::text, size_raw text DEFAULT NULL::text, color_raw text DEFAULT NULL::text, limit_n integer DEFAULT 48, offset_n integer DEFAULT 0)
 RETURNS TABLE(id uuid, original_url text, product_page_url text, monetized_product_url text, brand text, height_in numeric, weight_lb numeric, weight_display text, size_ordered_raw text, color_ordered_raw text, source_site text, created_at timestamp with time zone, score double precision)
 LANGUAGE plpgsql
AS $function$
BEGIN
  RETURN QUERY
  SELECT * FROM public.match_by_measurements(in_height, in_weight, in_bust, in_waist, in_hips, retailer, size_raw, color_raw, limit_n, offset_n);
END;
$function$
;

CREATE OR REPLACE FUNCTION public.parse_age_years(t text)
 RETURNS integer
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select case when t ~ '\d' then nullif(regexp_replace(lower(t), '[^0-9]', '', 'g'),'')::int else null end;
$function$
;

CREATE OR REPLACE FUNCTION public.parse_height_in(t text)
 RETURNS numeric
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
declare s text; feet text; inches text; num numeric;
begin
  if t is null then return null; end if;
  s := lower(regexp_replace(t, 'height[:\s]*', '', 'gi'));
  if s ~ '(\d+)\s*[''′]\s*(\d{1,2})' then
     select (m[1]), (m[2]) into feet, inches
     from regexp_matches(s, '(\d+)\s*[''′]\s*(\d{1,2})') as m;
     return feet::int*12 + inches::int;
  end if;
  if s ~ 'cm' then
     num := regexp_replace(s, '[^0-9\.]', '', 'g')::numeric;
     return round(num/2.54);
  end if;
  if s ~ '^\s*[4-7](\.\d+)?\s*$' then
     num := regexp_replace(s, '[^0-9\.]', '', 'g')::numeric;
     return round(num*12);
  end if;
  if s ~ '^\s*\d{2,3}\s*(in)?\s*$' then
     num := regexp_replace(s, '[^0-9]', '', 'g')::numeric;
     return num;
  end if;
  return null;
end $function$
;

CREATE OR REPLACE FUNCTION public.parse_inches(t text)
 RETURNS numeric
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
declare s text; num numeric;
begin
  if t is null then return null; end if;
  s := lower(t);
  if s ~ 'cm' then
     num := regexp_replace(s, '[^0-9\.]', '', 'g')::numeric;
     return round(num/2.54);
  end if;
  if s ~ '(\d+)\s*[''′]\s*(\d{1,2})' then
     return (regexp_replace(s, '.*?(\d+)\s*[''′]\s*(\d{1,2}).*', '\1', 'g')::int)*12
          + (regexp_replace(s, '.*?(\d+)\s*[''′]\s*(\d{1,2}).*', '\2', 'g')::int);
  end if;
  if s ~ '\d' then
     num := regexp_replace(s, '[^0-9\.]', '', 'g')::numeric;
     return round(num);
  end if;
  return null;
end $function$
;

CREATE OR REPLACE FUNCTION public.parse_weight_lb(t text)
 RETURNS numeric
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
declare s text; num numeric;
begin
  if t is null then return null; end if;
  s := lower(t);
  if s ~ 'kg' then
     num := regexp_replace(s, '[^0-9\.]', '', 'g')::numeric;
     return round(num*2.20462);
  end if;
  if s ~ 'st' then
     num := regexp_replace(s, '[^0-9\.]', '', 'g')::numeric;
     return round(num*14);
  end if;
  if s ~ '\d' then
     num := regexp_replace(s, '[^0-9\.]', '', 'g')::numeric;
     return round(num);
  end if;
  return null;
end $function$
;

CREATE OR REPLACE FUNCTION public.search_catalog_deprecated(q text DEFAULT NULL::text, size_raw text DEFAULT NULL::text, color_raw text DEFAULT NULL::text, retailer text DEFAULT NULL::text, min_height numeric DEFAULT NULL::numeric, max_height numeric DEFAULT NULL::numeric, start_date date DEFAULT NULL::date, end_date date DEFAULT NULL::date, limit_n integer DEFAULT 50, offset_n integer DEFAULT 0)
 RETURNS SETOF archive.images_public
 LANGUAGE plpgsql
AS $function$
BEGIN
  RETURN QUERY
  SELECT * FROM public.search_catalog(q, size_raw, color_raw, retailer, min_height, max_height, start_date, end_date, limit_n, offset_n);
END;
$function$
;

CREATE OR REPLACE FUNCTION public.update_search_event_metrics(p_id uuid, p_results_count integer, p_latency_ms integer)
 RETURNS void
 LANGUAGE sql
 SECURITY DEFINER
AS $function$
  update public.search_events
  set results_count = p_results_count,
      latency_ms = p_latency_ms
  where id = p_id;
$function$
;

grant delete on table "archive"."color_map" to "anon";

grant insert on table "archive"."color_map" to "anon";

grant references on table "archive"."color_map" to "anon";

grant select on table "archive"."color_map" to "anon";

grant trigger on table "archive"."color_map" to "anon";

grant truncate on table "archive"."color_map" to "anon";

grant update on table "archive"."color_map" to "anon";

grant delete on table "archive"."color_map" to "authenticated";

grant insert on table "archive"."color_map" to "authenticated";

grant references on table "archive"."color_map" to "authenticated";

grant select on table "archive"."color_map" to "authenticated";

grant trigger on table "archive"."color_map" to "authenticated";

grant truncate on table "archive"."color_map" to "authenticated";

grant update on table "archive"."color_map" to "authenticated";

grant delete on table "archive"."color_map" to "service_role";

grant insert on table "archive"."color_map" to "service_role";

grant references on table "archive"."color_map" to "service_role";

grant select on table "archive"."color_map" to "service_role";

grant trigger on table "archive"."color_map" to "service_role";

grant truncate on table "archive"."color_map" to "service_role";

grant update on table "archive"."color_map" to "service_role";

grant delete on table "archive"."image_vectors" to "service_role";

grant insert on table "archive"."image_vectors" to "service_role";

grant references on table "archive"."image_vectors" to "service_role";

grant select on table "archive"."image_vectors" to "service_role";

grant trigger on table "archive"."image_vectors" to "service_role";

grant truncate on table "archive"."image_vectors" to "service_role";

grant update on table "archive"."image_vectors" to "service_role";

grant delete on table "archive"."images_backup" to "anon";

grant insert on table "archive"."images_backup" to "anon";

grant references on table "archive"."images_backup" to "anon";

grant select on table "archive"."images_backup" to "anon";

grant trigger on table "archive"."images_backup" to "anon";

grant truncate on table "archive"."images_backup" to "anon";

grant update on table "archive"."images_backup" to "anon";

grant delete on table "archive"."images_backup" to "authenticated";

grant insert on table "archive"."images_backup" to "authenticated";

grant references on table "archive"."images_backup" to "authenticated";

grant select on table "archive"."images_backup" to "authenticated";

grant trigger on table "archive"."images_backup" to "authenticated";

grant truncate on table "archive"."images_backup" to "authenticated";

grant update on table "archive"."images_backup" to "authenticated";

grant delete on table "archive"."images_backup" to "service_role";

grant insert on table "archive"."images_backup" to "service_role";

grant references on table "archive"."images_backup" to "service_role";

grant select on table "archive"."images_backup" to "service_role";

grant trigger on table "archive"."images_backup" to "service_role";

grant truncate on table "archive"."images_backup" to "service_role";

grant update on table "archive"."images_backup" to "service_role";

grant delete on table "archive"."images_deprecated_2025_12_30" to "service_role";

grant insert on table "archive"."images_deprecated_2025_12_30" to "service_role";

grant references on table "archive"."images_deprecated_2025_12_30" to "service_role";

grant select on table "archive"."images_deprecated_2025_12_30" to "service_role";

grant trigger on table "archive"."images_deprecated_2025_12_30" to "service_role";

grant truncate on table "archive"."images_deprecated_2025_12_30" to "service_role";

grant update on table "archive"."images_deprecated_2025_12_30" to "service_role";

grant delete on table "archive"."images_import_dec2025_2" to "anon";

grant insert on table "archive"."images_import_dec2025_2" to "anon";

grant references on table "archive"."images_import_dec2025_2" to "anon";

grant select on table "archive"."images_import_dec2025_2" to "anon";

grant trigger on table "archive"."images_import_dec2025_2" to "anon";

grant truncate on table "archive"."images_import_dec2025_2" to "anon";

grant update on table "archive"."images_import_dec2025_2" to "anon";

grant delete on table "archive"."images_import_dec2025_2" to "authenticated";

grant insert on table "archive"."images_import_dec2025_2" to "authenticated";

grant references on table "archive"."images_import_dec2025_2" to "authenticated";

grant select on table "archive"."images_import_dec2025_2" to "authenticated";

grant trigger on table "archive"."images_import_dec2025_2" to "authenticated";

grant truncate on table "archive"."images_import_dec2025_2" to "authenticated";

grant update on table "archive"."images_import_dec2025_2" to "authenticated";

grant delete on table "archive"."images_import_dec2025_2" to "service_role";

grant insert on table "archive"."images_import_dec2025_2" to "service_role";

grant references on table "archive"."images_import_dec2025_2" to "service_role";

grant select on table "archive"."images_import_dec2025_2" to "service_role";

grant trigger on table "archive"."images_import_dec2025_2" to "service_role";

grant truncate on table "archive"."images_import_dec2025_2" to "service_role";

grant update on table "archive"."images_import_dec2025_2" to "service_role";

grant delete on table "archive"."raw_fwm_import" to "anon";

grant insert on table "archive"."raw_fwm_import" to "anon";

grant references on table "archive"."raw_fwm_import" to "anon";

grant select on table "archive"."raw_fwm_import" to "anon";

grant trigger on table "archive"."raw_fwm_import" to "anon";

grant truncate on table "archive"."raw_fwm_import" to "anon";

grant update on table "archive"."raw_fwm_import" to "anon";

grant delete on table "archive"."raw_fwm_import" to "authenticated";

grant insert on table "archive"."raw_fwm_import" to "authenticated";

grant references on table "archive"."raw_fwm_import" to "authenticated";

grant select on table "archive"."raw_fwm_import" to "authenticated";

grant trigger on table "archive"."raw_fwm_import" to "authenticated";

grant truncate on table "archive"."raw_fwm_import" to "authenticated";

grant update on table "archive"."raw_fwm_import" to "authenticated";

grant delete on table "archive"."raw_fwm_import" to "service_role";

grant insert on table "archive"."raw_fwm_import" to "service_role";

grant references on table "archive"."raw_fwm_import" to "service_role";

grant select on table "archive"."raw_fwm_import" to "service_role";

grant trigger on table "archive"."raw_fwm_import" to "service_role";

grant truncate on table "archive"."raw_fwm_import" to "service_role";

grant update on table "archive"."raw_fwm_import" to "service_role";

grant delete on table "archive"."size_map" to "anon";

grant insert on table "archive"."size_map" to "anon";

grant references on table "archive"."size_map" to "anon";

grant select on table "archive"."size_map" to "anon";

grant trigger on table "archive"."size_map" to "anon";

grant truncate on table "archive"."size_map" to "anon";

grant update on table "archive"."size_map" to "anon";

grant delete on table "archive"."size_map" to "authenticated";

grant insert on table "archive"."size_map" to "authenticated";

grant references on table "archive"."size_map" to "authenticated";

grant select on table "archive"."size_map" to "authenticated";

grant trigger on table "archive"."size_map" to "authenticated";

grant truncate on table "archive"."size_map" to "authenticated";

grant update on table "archive"."size_map" to "authenticated";

grant delete on table "archive"."size_map" to "service_role";

grant insert on table "archive"."size_map" to "service_role";

grant references on table "archive"."size_map" to "service_role";

grant select on table "archive"."size_map" to "service_role";

grant trigger on table "archive"."size_map" to "service_role";

grant truncate on table "archive"."size_map" to "service_role";

grant update on table "archive"."size_map" to "service_role";

grant delete on table "public"."archive.images_backup_20260320_063904" to "anon";

grant insert on table "public"."archive.images_backup_20260320_063904" to "anon";

grant references on table "public"."archive.images_backup_20260320_063904" to "anon";

grant select on table "public"."archive.images_backup_20260320_063904" to "anon";

grant trigger on table "public"."archive.images_backup_20260320_063904" to "anon";

grant truncate on table "public"."archive.images_backup_20260320_063904" to "anon";

grant update on table "public"."archive.images_backup_20260320_063904" to "anon";

grant delete on table "public"."archive.images_backup_20260320_063904" to "authenticated";

grant insert on table "public"."archive.images_backup_20260320_063904" to "authenticated";

grant references on table "public"."archive.images_backup_20260320_063904" to "authenticated";

grant select on table "public"."archive.images_backup_20260320_063904" to "authenticated";

grant trigger on table "public"."archive.images_backup_20260320_063904" to "authenticated";

grant truncate on table "public"."archive.images_backup_20260320_063904" to "authenticated";

grant update on table "public"."archive.images_backup_20260320_063904" to "authenticated";

grant delete on table "public"."archive.images_backup_20260320_063904" to "service_role";

grant insert on table "public"."archive.images_backup_20260320_063904" to "service_role";

grant references on table "public"."archive.images_backup_20260320_063904" to "service_role";

grant select on table "public"."archive.images_backup_20260320_063904" to "service_role";

grant trigger on table "public"."archive.images_backup_20260320_063904" to "service_role";

grant truncate on table "public"."archive.images_backup_20260320_063904" to "service_role";

grant update on table "public"."archive.images_backup_20260320_063904" to "service_role";

grant delete on table "public"."clothing_types" to "anon";

grant insert on table "public"."clothing_types" to "anon";

grant references on table "public"."clothing_types" to "anon";

grant select on table "public"."clothing_types" to "anon";

grant trigger on table "public"."clothing_types" to "anon";

grant truncate on table "public"."clothing_types" to "anon";

grant update on table "public"."clothing_types" to "anon";

grant delete on table "public"."clothing_types" to "authenticated";

grant insert on table "public"."clothing_types" to "authenticated";

grant references on table "public"."clothing_types" to "authenticated";

grant select on table "public"."clothing_types" to "authenticated";

grant trigger on table "public"."clothing_types" to "authenticated";

grant truncate on table "public"."clothing_types" to "authenticated";

grant update on table "public"."clothing_types" to "authenticated";

grant delete on table "public"."clothing_types" to "service_role";

grant insert on table "public"."clothing_types" to "service_role";

grant references on table "public"."clothing_types" to "service_role";

grant select on table "public"."clothing_types" to "service_role";

grant trigger on table "public"."clothing_types" to "service_role";

grant truncate on table "public"."clothing_types" to "service_role";

grant update on table "public"."clothing_types" to "service_role";

grant delete on table "public"."images" to "anon";

grant insert on table "public"."images" to "anon";

grant references on table "public"."images" to "anon";

grant select on table "public"."images" to "anon";

grant trigger on table "public"."images" to "anon";

grant truncate on table "public"."images" to "anon";

grant update on table "public"."images" to "anon";

grant delete on table "public"."images" to "authenticated";

grant insert on table "public"."images" to "authenticated";

grant references on table "public"."images" to "authenticated";

grant select on table "public"."images" to "authenticated";

grant trigger on table "public"."images" to "authenticated";

grant truncate on table "public"."images" to "authenticated";

grant update on table "public"."images" to "authenticated";

grant delete on table "public"."images" to "service_role";

grant insert on table "public"."images" to "service_role";

grant references on table "public"."images" to "service_role";

grant select on table "public"."images" to "service_role";

grant trigger on table "public"."images" to "service_role";

grant truncate on table "public"."images" to "service_role";

grant update on table "public"."images" to "service_role";

grant delete on table "public"."images_backup_20260320" to "anon";

grant insert on table "public"."images_backup_20260320" to "anon";

grant references on table "public"."images_backup_20260320" to "anon";

grant select on table "public"."images_backup_20260320" to "anon";

grant trigger on table "public"."images_backup_20260320" to "anon";

grant truncate on table "public"."images_backup_20260320" to "anon";

grant update on table "public"."images_backup_20260320" to "anon";

grant delete on table "public"."images_backup_20260320" to "authenticated";

grant insert on table "public"."images_backup_20260320" to "authenticated";

grant references on table "public"."images_backup_20260320" to "authenticated";

grant select on table "public"."images_backup_20260320" to "authenticated";

grant trigger on table "public"."images_backup_20260320" to "authenticated";

grant truncate on table "public"."images_backup_20260320" to "authenticated";

grant update on table "public"."images_backup_20260320" to "authenticated";

grant delete on table "public"."images_backup_20260320" to "service_role";

grant insert on table "public"."images_backup_20260320" to "service_role";

grant references on table "public"."images_backup_20260320" to "service_role";

grant select on table "public"."images_backup_20260320" to "service_role";

grant trigger on table "public"."images_backup_20260320" to "service_role";

grant truncate on table "public"."images_backup_20260320" to "service_role";

grant update on table "public"."images_backup_20260320" to "service_role";

grant delete on table "public"."images_staging" to "anon";

grant insert on table "public"."images_staging" to "anon";

grant references on table "public"."images_staging" to "anon";

grant select on table "public"."images_staging" to "anon";

grant trigger on table "public"."images_staging" to "anon";

grant truncate on table "public"."images_staging" to "anon";

grant update on table "public"."images_staging" to "anon";

grant delete on table "public"."images_staging" to "authenticated";

grant insert on table "public"."images_staging" to "authenticated";

grant references on table "public"."images_staging" to "authenticated";

grant select on table "public"."images_staging" to "authenticated";

grant trigger on table "public"."images_staging" to "authenticated";

grant truncate on table "public"."images_staging" to "authenticated";

grant update on table "public"."images_staging" to "authenticated";

grant delete on table "public"."images_staging" to "service_role";

grant insert on table "public"."images_staging" to "service_role";

grant references on table "public"."images_staging" to "service_role";

grant select on table "public"."images_staging" to "service_role";

grant trigger on table "public"."images_staging" to "service_role";

grant truncate on table "public"."images_staging" to "service_role";

grant update on table "public"."images_staging" to "service_role";

grant delete on table "public"."search_events" to "anon";

grant insert on table "public"."search_events" to "anon";

grant references on table "public"."search_events" to "anon";

grant select on table "public"."search_events" to "anon";

grant trigger on table "public"."search_events" to "anon";

grant truncate on table "public"."search_events" to "anon";

grant update on table "public"."search_events" to "anon";

grant delete on table "public"."search_events" to "authenticated";

grant insert on table "public"."search_events" to "authenticated";

grant references on table "public"."search_events" to "authenticated";

grant select on table "public"."search_events" to "authenticated";

grant trigger on table "public"."search_events" to "authenticated";

grant truncate on table "public"."search_events" to "authenticated";

grant update on table "public"."search_events" to "authenticated";

grant delete on table "public"."search_events" to "service_role";

grant insert on table "public"."search_events" to "service_role";

grant references on table "public"."search_events" to "service_role";

grant select on table "public"."search_events" to "service_role";

grant trigger on table "public"."search_events" to "service_role";

grant truncate on table "public"."search_events" to "service_role";

grant update on table "public"."search_events" to "service_role";


  create policy "insert search events"
  on "public"."search_events"
  as permissive
  for insert
  to anon, authenticated
with check (true);



  create policy "update search events"
  on "public"."search_events"
  as permissive
  for update
  to anon, authenticated
using (true)
with check (true);



