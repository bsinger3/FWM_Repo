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

create or replace function staging.category_from_product_signal(
  normalized_product_page_url text,
  observed_clothing_type_ids text[] default '{}'::text[]
)
returns table(
  mother_category_id text,
  clothing_type_tag_ids text[],
  category_confidence text,
  category_evidence text,
  needs_manual_review boolean
)
language plpgsql
stable
as $function$
declare
  signal text := regexp_replace(coalesce(normalized_product_page_url, ''), '^https?://[^/]+/?', '');
  observed text[];
  observed_mothers text[];
  fallback_tag text;
  fallback_mother text;
  tags text[] := '{}'::text[];
  mother text;
  evidence_parts text[] := '{}'::text[];
  confidence text := 'low';
begin
  signal := regexp_replace(signal, '[^a-z0-9]+', ' ', 'g');
  observed := coalesce(observed_clothing_type_ids, '{}'::text[]);

  if signal ~ '\m(jean|jeans|denim)\M' then
    mother := 'bottoms';
    tags := tags || array['jeans', 'pants', 'bottoms'];
    evidence_parts := evidence_parts || array['url: jeans/denim'];
  elsif signal ~ '\m(pant|pants|trouser|trousers|slack|slacks)\M' then
    mother := 'bottoms';
    tags := tags || array['pants', 'bottoms'];
    evidence_parts := evidence_parts || array['url: pants/trousers'];
  elsif signal ~ '\m(legging|leggings|tight|tights)\M' then
    mother := 'bottoms';
    tags := tags || array['leggings', 'bottoms'];
    evidence_parts := evidence_parts || array['url: leggings'];
  elsif signal ~ '\m(short|shorts)\M' then
    mother := 'bottoms';
    tags := tags || array['shorts', 'bottoms'];
    evidence_parts := evidence_parts || array['url: shorts'];
  elsif signal ~ '\m(skirt|skirts)\M' then
    mother := 'bottoms';
    tags := tags || array['skirt', 'bottoms'];
    evidence_parts := evidence_parts || array['url: skirt'];
  elsif signal ~ '\m(gown|gowns|bridesmaid|formal|evening)\M' then
    mother := 'dresses';
    tags := tags || array['gown', 'dress', 'dresses'];
    evidence_parts := evidence_parts || array['url: gown/formal'];
  elsif signal ~ '\m(dress|dresses|sundress)\M' then
    mother := 'dresses';
    tags := tags || array['dress', 'dresses'];
    evidence_parts := evidence_parts || array['url: dress'];
  elsif signal ~ '\m(bodysuit|bodysuits)\M' then
    mother := 'bodysuits';
    tags := tags || array['bodysuit'];
    evidence_parts := evidence_parts || array['url: bodysuit'];
  elsif signal ~ '\m(bikini|bikinis)\M' then
    mother := 'swimwear';
    tags := tags || array['bikini', 'swimwear'];
    evidence_parts := evidence_parts || array['url: bikini'];
  elsif signal ~ '\m(swim|swimsuit|swimwear|one piece swimsuit|one-piece swimsuit)\M' then
    mother := 'swimwear';
    tags := tags || array['one-piece-swimsuit', 'swimwear'];
    evidence_parts := evidence_parts || array['url: swimwear'];
  elsif signal ~ '\m(jacket|jackets|blazer|blazers|shacket)\M' then
    mother := 'outerwear';
    tags := tags || array['jacket'];
    evidence_parts := evidence_parts || array['url: jacket/blazer'];
  elsif signal ~ '\m(coat|coats|parka|trench)\M' then
    mother := 'outerwear';
    tags := tags || array['coat'];
    evidence_parts := evidence_parts || array['url: coat'];
  elsif signal ~ '\m(bra|bras|bralette|bralettes)\M' then
    mother := 'intimates';
    tags := tags || array['bra'];
    evidence_parts := evidence_parts || array['url: bra'];
  elsif signal ~ '\m(underwear|panty|panties|brief|briefs|thong|thongs)\M' then
    mother := 'intimates';
    tags := tags || array['underwear'];
    evidence_parts := evidence_parts || array['url: underwear'];
  elsif signal ~ '\m(set|sets)\M' then
    mother := 'sets';
    tags := tags || array['sets'];
    evidence_parts := evidence_parts || array['url: set'];
  elsif signal ~ '\m(blouse|blouses)\M' then
    mother := 'tops';
    tags := tags || array['blouse', 'top', 'tops'];
    evidence_parts := evidence_parts || array['url: blouse'];
  elsif signal ~ '\m(shirt|shirts|button down|buttondown)\M' then
    mother := 'tops';
    tags := tags || array['shirt', 'top', 'tops'];
    evidence_parts := evidence_parts || array['url: shirt'];
  elsif signal ~ '\m(tee|tees|t shirt|tshirt)\M' then
    mother := 'tops';
    tags := tags || array['tee', 'top', 'tops'];
    evidence_parts := evidence_parts || array['url: tee'];
  elsif signal ~ '\m(tank|cami|camisole)\M' then
    mother := 'tops';
    tags := tags || array['tank', 'top', 'tops'];
    evidence_parts := evidence_parts || array['url: tank/cami'];
  elsif signal ~ '\m(sweater|sweaters|cardigan|pullover)\M' then
    mother := 'tops';
    tags := tags || array['sweater', 'top', 'tops'];
    evidence_parts := evidence_parts || array['url: sweater/cardigan'];
  elsif signal ~ '\m(top|tops)\M' then
    mother := 'tops';
    tags := tags || array['top', 'tops'];
    evidence_parts := evidence_parts || array['url: top'];
  end if;

  select array_agg(distinct ct.mother_category_id)
  into observed_mothers
  from unnest(observed) as observed_id
  join staging.clothing_type_tags ct on ct.id = observed_id;

  select observed_id, ct.mother_category_id
  into fallback_tag, fallback_mother
  from unnest(observed) as observed_id
  join staging.clothing_type_tags ct on ct.id = observed_id
  order by ct.search_boost desc, ct.sort_order
  limit 1;

  if fallback_tag is not null then
    tags := tags || array[fallback_tag, fallback_mother];
    evidence_parts := evidence_parts || array[format('existing clothing_type_id: %s', fallback_tag)];
  end if;

  if mother is null and fallback_mother is not null then
    mother := fallback_mother;
  end if;

  if mother is null then
    mother := 'other';
    tags := tags || array['other'];
    evidence_parts := evidence_parts || array['fallback: no URL or existing clothing_type_id signal'];
  end if;

  select coalesce(array_agg(distinct tag_id order by tag_id), array['other'])
  into tags
  from unnest(tags) as tag_id
  join staging.clothing_type_tags ct on ct.id = tag_id;

  if evidence_parts && array['fallback: no URL or existing clothing_type_id signal'] then
    confidence := 'low';
  elsif array_length(observed_mothers, 1) > 0 and not mother = any(observed_mothers) then
    confidence := 'medium';
  elsif array_length(evidence_parts, 1) > 1 then
    confidence := 'high';
  else
    confidence := 'medium';
  end if;

  return query
  select
    mother,
    tags,
    confidence,
    array_to_string(evidence_parts, '; '),
    confidence = 'low'
      or coalesce(array_length(observed_mothers, 1) > 0 and not mother = any(observed_mothers), false);
end;
$function$;

create or replace function staging.refresh_product_category_staging()
returns table(
  product_pages_inserted integer,
  tag_links_inserted integer,
  image_links_inserted integer,
  low_confidence_products integer
)
language plpgsql
security definer
set search_path = staging, public, pg_temp
as $function$
declare
  product_count integer := 0;
  tag_count integer := 0;
  image_count integer := 0;
  low_count integer := 0;
begin
  truncate table
    staging.product_page_clothing_type_tags,
    staging.product_page_image_sources,
    staging.product_pages;

  with source_images as (
    select
      i.id as image_id,
      staging.normalize_product_url(
        coalesce(nullif(i.product_page_url_display, ''), nullif(i.monetized_product_url_display, ''))
      ) as normalized_product_page_url,
      i.product_page_url_display,
      i.monetized_product_url_display,
      nullif(i.source_site_display, '') as source_site_display,
      nullif(i.brand, '') as brand,
      nullif(i.clothing_type_id, '') as clothing_type_id,
      i.created_at_display
    from public.images i
    where staging.normalize_product_url(
      coalesce(nullif(i.product_page_url_display, ''), nullif(i.monetized_product_url_display, ''))
    ) is not null
  ),
  product_rollup as (
    select
      normalized_product_page_url,
      (array_remove(array_agg(source_site_display order by created_at_display desc), null::text))[1] as source_site,
      (array_remove(array_agg(brand order by created_at_display desc), null::text))[1] as brand,
      coalesce(array_agg(distinct clothing_type_id) filter (where clothing_type_id is not null), '{}'::text[]) as observed_clothing_type_ids,
      count(*)::integer as image_row_count,
      min(created_at_display) as first_seen_at,
      max(created_at_display) as last_seen_at
    from source_images
    group by normalized_product_page_url
  ),
  classified as (
    select
      pr.*,
      c.mother_category_id,
      c.clothing_type_tag_ids,
      c.category_confidence,
      c.category_evidence,
      c.needs_manual_review
    from product_rollup pr
    cross join lateral staging.category_from_product_signal(
      pr.normalized_product_page_url,
      pr.observed_clothing_type_ids
    ) c
  ),
  inserted as (
    insert into staging.product_pages (
      normalized_product_page_url,
      source_site,
      brand,
      mother_category_id,
      category_confidence,
      category_evidence,
      needs_manual_review,
      observed_clothing_type_ids,
      image_row_count,
      first_seen_at,
      last_seen_at,
      raw_metadata,
      classified_at,
      updated_at
    )
    select
      normalized_product_page_url,
      coalesce(
        source_site,
        nullif(regexp_replace(normalized_product_page_url, '^https?://([^/]+).*$'::text, '\1'), normalized_product_page_url)
      ) as source_site,
      brand,
      mother_category_id,
      category_confidence,
      category_evidence,
      needs_manual_review,
      observed_clothing_type_ids,
      image_row_count,
      first_seen_at,
      last_seen_at,
      jsonb_build_object('staging_source', 'public.images distinct product links'),
      now(),
      now()
    from classified
    returning 1
  )
  select count(*)::integer into product_count from inserted;

  with source_images as (
    select
      i.id as image_id,
      staging.normalize_product_url(
        coalesce(nullif(i.product_page_url_display, ''), nullif(i.monetized_product_url_display, ''))
      ) as normalized_product_page_url,
      i.product_page_url_display,
      i.monetized_product_url_display,
      nullif(i.source_site_display, '') as source_site_display,
      nullif(i.brand, '') as brand,
      nullif(i.clothing_type_id, '') as clothing_type_id,
      i.created_at_display
    from public.images i
    where staging.normalize_product_url(
      coalesce(nullif(i.product_page_url_display, ''), nullif(i.monetized_product_url_display, ''))
    ) is not null
  )
  insert into staging.product_page_image_sources (
    product_page_id,
    image_id,
    original_product_page_url,
    original_monetized_product_url,
    source_site,
    brand,
    clothing_type_id,
    created_at_display
  )
  select
    pp.id,
    si.image_id,
    si.product_page_url_display,
    si.monetized_product_url_display,
    si.source_site_display,
    si.brand,
    si.clothing_type_id,
    si.created_at_display
  from source_images si
  join staging.product_pages pp
    on pp.normalized_product_page_url = si.normalized_product_page_url
  on conflict (product_page_id, image_id) do nothing;

  get diagnostics image_count = row_count;

  insert into staging.product_page_clothing_type_tags (
    product_page_id,
    clothing_type_id,
    evidence
  )
  select
    pp.id,
    tag_id,
    pp.category_evidence
  from staging.product_pages pp
  cross join lateral staging.category_from_product_signal(
    pp.normalized_product_page_url,
    pp.observed_clothing_type_ids
  ) c
  cross join lateral unnest(c.clothing_type_tag_ids) as tag_id
  on conflict (product_page_id, clothing_type_id) do update set
    evidence = excluded.evidence;

  get diagnostics tag_count = row_count;

  select count(*)::integer
  into low_count
  from staging.product_pages
  where category_confidence = 'low' or needs_manual_review;

  product_pages_inserted := product_count;
  tag_links_inserted := tag_count;
  image_links_inserted := image_count;
  low_confidence_products := low_count;
  return next;
end;
$function$;

grant execute on function staging.normalize_product_url(text) to service_role;
grant execute on function staging.category_from_product_signal(text, text[]) to service_role;
grant execute on function staging.refresh_product_category_staging() to service_role;

select * from staging.refresh_product_category_staging();
