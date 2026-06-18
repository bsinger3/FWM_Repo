-- Dev-only bootstrap for staging.product_pages.
-- The production migration history already has product-page staging schema, but
-- the dev project may start emptier. This creates the existing staging shape
-- needed by the images refresh without touching production migrations.

create schema if not exists staging;

comment on schema staging is 'Private staging schema for product-level category/tag enrichment. Not used by the live website.';

revoke all on schema staging from public;
grant usage on schema staging to postgres;
grant usage on schema staging to service_role;

create table if not exists staging.clothing_mother_categories (
  id text primary key,
  label text not null,
  display_label text not null,
  sort_order integer not null default 999,
  frontend_sort_order integer not null default 999,
  is_frontend_filter boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists staging.clothing_type_tags (
  id text primary key,
  mother_category_id text not null references staging.clothing_mother_categories(id),
  label text not null,
  display_label text not null,
  aliases text[] not null default '{}',
  sort_order integer not null default 999,
  frontend_sort_order integer not null default 999,
  is_search_tag boolean not null default true,
  is_frontend_filter boolean not null default true,
  search_boost numeric not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists staging.product_pages (
  id uuid primary key default gen_random_uuid(),
  normalized_product_page_url text unique not null,
  source_site text,
  brand text,
  product_title_raw text,
  product_category_raw text,
  catalog_image_url text,
  catalog_image_urls text[] not null default '{}',
  catalog_image_source text,
  catalog_image_fetched_at timestamptz,
  catalog_image_fetch_status text,
  catalog_image_fetch_error text,
  mother_category_id text references staging.clothing_mother_categories(id),
  category_confidence text not null default 'low'
    check (category_confidence in ('high', 'medium', 'low')),
  category_evidence text,
  needs_manual_review boolean not null default true,
  observed_clothing_type_ids text[] not null default '{}',
  image_row_count integer not null default 0,
  first_seen_at timestamptz,
  last_seen_at timestamptz,
  populated_from text not null default 'public.images',
  raw_metadata jsonb not null default '{}'::jsonb,
  classified_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists staging.product_page_clothing_type_tags (
  product_page_id uuid not null references staging.product_pages(id) on delete cascade,
  clothing_type_id text not null references staging.clothing_type_tags(id),
  evidence text,
  created_at timestamptz not null default now(),
  primary key (product_page_id, clothing_type_id)
);

create table if not exists staging.product_page_image_sources (
  product_page_id uuid not null references staging.product_pages(id) on delete cascade,
  image_id uuid not null,
  original_product_page_url text,
  original_monetized_product_url text,
  source_site text,
  brand text,
  clothing_type_id text,
  created_at_display timestamptz,
  created_at timestamptz not null default now(),
  primary key (product_page_id, image_id)
);

create index if not exists product_pages_mother_category_idx
  on staging.product_pages (mother_category_id);

create index if not exists product_pages_source_site_idx
  on staging.product_pages (source_site);

create index if not exists product_page_tags_clothing_type_idx
  on staging.product_page_clothing_type_tags (clothing_type_id);

create index if not exists product_page_image_sources_image_id_idx
  on staging.product_page_image_sources (image_id);

grant select, insert, update, delete on all tables in schema staging to service_role;
grant usage, select on all sequences in schema staging to service_role;

insert into staging.clothing_mother_categories
  (id, label, display_label, sort_order, frontend_sort_order, is_frontend_filter)
values
  ('tops', 'Tops', 'Tops', 10, 10, true),
  ('bottoms', 'Bottoms', 'Bottoms', 20, 20, true),
  ('dresses', 'Dresses', 'Dresses', 30, 30, true),
  ('jumpsuit', 'Jumpsuit', 'Jumpsuit', 35, 35, true),
  ('romper', 'Romper', 'Romper', 36, 36, true),
  ('bodysuits', 'Bodysuits', 'Bodysuits', 40, 40, true),
  ('swimwear', 'Swimwear', 'Swimwear', 50, 50, true),
  ('outerwear', 'Outerwear', 'Outerwear', 60, 60, true),
  ('intimates', 'Intimates', 'Intimates', 70, 70, true),
  ('sets', 'Sets', 'Sets', 80, 80, true),
  ('other', 'Other', 'Other', 999, 999, true)
on conflict (id) do update set
  label = excluded.label,
  display_label = excluded.display_label,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  is_frontend_filter = excluded.is_frontend_filter,
  updated_at = now();

insert into staging.clothing_type_tags
  (id, mother_category_id, label, display_label, aliases, sort_order, frontend_sort_order, search_boost)
values
  ('tops', 'tops', 'Tops', 'Tops', array['top'], 10, 10, 1),
  ('top', 'tops', 'Top', 'Top', array['tops'], 20, 20, 1.1),
  ('blouse', 'tops', 'Blouse', 'Blouse', array['blouses'], 30, 30, 1.2),
  ('shirt', 'tops', 'Shirt', 'Shirt', array['shirts', 'button down', 'button-down'], 40, 40, 1.1),
  ('tee', 'tops', 'Tee', 'Tee', array['t-shirt', 't shirt', 'tshirt'], 50, 50, 1.1),
  ('tank', 'tops', 'Tank', 'Tank', array['tank top', 'camisole', 'cami'], 60, 60, 1.1),
  ('sweater', 'tops', 'Sweater', 'Sweater', array['sweaters', 'pullover', 'cardigan'], 70, 70, 1.1),
  ('bottoms', 'bottoms', 'Bottoms', 'Bottoms', array['bottom'], 10, 10, 1),
  ('jeans', 'bottoms', 'Jeans', 'Jeans', array['jean', 'denim'], 20, 20, 1.4),
  ('pants', 'bottoms', 'Pants', 'Pants', array['pant', 'trousers', 'slacks'], 30, 30, 1.3),
  ('trousers', 'bottoms', 'Trousers', 'Trousers', array['trouser', 'dress pants'], 40, 40, 1.2),
  ('leggings', 'bottoms', 'Leggings', 'Leggings', array['legging', 'tights'], 50, 50, 1.2),
  ('shorts', 'bottoms', 'Shorts', 'Shorts', array['short'], 60, 60, 1.2),
  ('skirt', 'bottoms', 'Skirt', 'Skirt', array['skirts'], 70, 70, 1.2),
  ('dresses', 'dresses', 'Dresses', 'Dresses', array['dress'], 10, 10, 1),
  ('dress', 'dresses', 'Dress', 'Dress', array['dresses', 'sundress', 'maxi dress', 'midi dress', 'mini dress'], 20, 20, 1.4),
  ('gown', 'dresses', 'Gown', 'Gown', array['formal dress', 'evening gown', 'bridesmaid dress'], 30, 30, 1.3),
  ('jumpsuit', 'jumpsuit', 'Jumpsuit', 'Jumpsuit', array['jumpsuits', 'jump suit'], 10, 10, 1.4),
  ('romper', 'romper', 'Romper', 'Romper', array['rompers', 'playsuit', 'play suit'], 10, 10, 1.4),
  ('bodysuit', 'bodysuits', 'Bodysuit', 'Bodysuit', array['bodysuits', 'one piece top'], 20, 20, 1.2),
  ('swimwear', 'swimwear', 'Swimwear', 'Swimwear', array['swimsuit', 'bathing suit'], 10, 10, 1),
  ('one-piece-swimsuit', 'swimwear', 'One-Piece Swimsuit', 'One-Piece Swimsuit', array['one piece swimsuit', 'one-piece', 'one piece swim'], 20, 20, 1.3),
  ('bikini', 'swimwear', 'Bikini', 'Bikini', array['bikinis', 'two piece swimsuit', 'two-piece swimsuit'], 30, 30, 1.3),
  ('jacket', 'outerwear', 'Jacket', 'Jacket', array['jackets', 'blazer', 'shacket'], 20, 20, 1.2),
  ('coat', 'outerwear', 'Coat', 'Coat', array['coats', 'parka', 'trench'], 30, 30, 1.2),
  ('bra', 'intimates', 'Bra', 'Bra', array['bras', 'bralette', 'sports bra'], 20, 20, 1.4),
  ('underwear', 'intimates', 'Underwear', 'Underwear', array['panty', 'panties', 'briefs', 'thong'], 30, 30, 1.2),
  ('sets', 'sets', 'Sets', 'Sets', array['set', 'matching set', 'two piece set'], 10, 10, 1),
  ('other', 'other', 'Other', 'Other', array[]::text[], 999, 999, 0.1)
on conflict (id) do update set
  mother_category_id = excluded.mother_category_id,
  label = excluded.label,
  display_label = excluded.display_label,
  aliases = excluded.aliases,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  search_boost = excluded.search_boost,
  updated_at = now();

create or replace function staging.normalize_product_url(raw_url text)
returns text
language sql
immutable
as $function$
  select nullif(
    regexp_replace(
      regexp_replace(
        regexp_replace(
          lower(btrim(coalesce(raw_url, ''))),
          '#.*$',
          ''
        ),
        '\?.*$',
        ''
      ),
      '/+$',
      ''
    ),
    ''
  );
$function$;
