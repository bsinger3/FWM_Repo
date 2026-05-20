insert into staging.clothing_type_tags
  (id, mother_category_id, label, display_label, aliases, sort_order, frontend_sort_order, search_boost)
values
  ('vest', 'tops', 'Vest', 'Vest', array['vests'], 90, 90, 1.15),
  ('bustier', 'tops', 'Bustier', 'Bustier', array['bustiers', 'corset', 'corsets', 'bandeau', 'bandeaus'], 95, 95, 1.2),
  ('caftan', 'dresses', 'Caftan', 'Caftan', array['kaftan', 'kaftans', 'caftans'], 40, 40, 1.15),
  ('coveralls', 'jumpsuits-rompers', 'Coveralls', 'Coveralls', array['coverall', 'catsuit', 'catsuits', 'snowsuit', 'snowsuits'], 50, 50, 1.2),
  ('suit', 'sets', 'Suit', 'Suit', array['suits', 'leisure suit'], 20, 20, 1.1),
  ('button-up', 'tops', 'Button-Up Shirt', 'Button-Up Shirt', array['button up', 'button-up', 'button down', 'button-down'], 45, 45, 1.2),
  ('halter', 'tops', 'Halter Top', 'Halter Top', array['halters'], 55, 55, 1.1),
  ('corduroy-pants', 'bottoms', 'Corduroy Pants', 'Corduroy Pants', array['cords', 'corduroys'], 38, 38, 1.15)
on conflict (id) do update set
  mother_category_id = excluded.mother_category_id,
  label = excluded.label,
  display_label = excluded.display_label,
  aliases = excluded.aliases,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  search_boost = excluded.search_boost,
  updated_at = now();

create or replace function staging.infer_product_title_from_url(normalized_product_page_url text)
returns text
language sql
immutable
as $function$
  with path_parts as (
    select regexp_replace(coalesce(normalized_product_page_url, ''), '^https?://[^/]+/?', '') as path
  ),
  slug_parts as (
    select nullif(
      regexp_replace(
        regexp_replace(
          (regexp_split_to_array(path, '/'))[array_length(regexp_split_to_array(path, '/'), 1)],
          '[0-9]+$',
          ''
        ),
        '[_-]+',
        ' ',
        'g'
      ),
      ''
    ) as slug
    from path_parts
  )
  select case
    when slug is null or slug ~ '^[0-9]+$' then null
    else initcap(slug)
  end
  from slug_parts;
$function$;

create or replace function staging.infer_brand_from_product_url(normalized_product_page_url text)
returns text
language sql
immutable
as $function$
  with parts as (
    select
      regexp_replace(lower(coalesce(normalized_product_page_url, '')), '^https?://(www[.])?([^/]+).*$'::text, '\2') as host,
      regexp_replace(lower(coalesce(normalized_product_page_url, '')), '^https?://[^/]+/?', '') as path
  ),
  designer as (
    select
      case
        when path like 'shop/designers/%' then split_part(regexp_replace(path, '^shop/designers/', ''), '/', 1)
        else null
      end as designer_slug,
      host
    from parts
  )
  select initcap(regexp_replace(coalesce(nullif(designer_slug, ''), split_part(host, '.', 1)), '[_-]+', ' ', 'g'))
  from designer;
$function$;

create or replace function staging.category_from_product_signal(
  normalized_product_page_url text,
  observed_clothing_type_ids text[] default '{}'::text[],
  product_title_raw text default null
)
returns table(
  mother_category_id text,
  clothing_type_tag_ids text[],
  product_category_raw text,
  category_confidence text,
  category_evidence text,
  needs_manual_review boolean
)
language plpgsql
stable
as $function$
declare
  signal text := concat_ws(' ', normalized_product_page_url, product_title_raw);
  observed text[];
  observed_mothers text[];
  fallback_tag text;
  fallback_mother text;
  tags text[] := '{}'::text[];
  mother text;
  raw_category text;
  evidence_parts text[] := '{}'::text[];
  confidence text := 'low';
begin
  signal := regexp_replace(regexp_replace(lower(coalesce(signal, '')), '^https?://[^/]+/?', ''), '[^a-z0-9]+', ' ', 'g');
  signal := regexp_replace(signal, '([a-z]+)[0-9]+\M', '\1', 'g');
  observed := array_remove(coalesce(observed_clothing_type_ids, '{}'::text[]), 'other');

  if signal ~ '\m(culotte|culottes)\M' then
    mother := 'bottoms'; raw_category := 'culottes'; tags := tags || array['culottes', 'pants', 'bottoms']; evidence_parts := evidence_parts || array['product signal: culottes'];
  elsif signal ~ '\m(jogger|joggers)\M' then
    mother := 'bottoms'; raw_category := 'joggers'; tags := tags || array['joggers', 'pants', 'bottoms']; evidence_parts := evidence_parts || array['product signal: joggers'];
  elsif signal ~ '\m(sweatpant|sweatpants)\M' then
    mother := 'bottoms'; raw_category := 'sweatpants'; tags := tags || array['sweatpants', 'pants', 'bottoms']; evidence_parts := evidence_parts || array['product signal: sweatpants'];
  elsif signal ~ '\m(cord|cords|corduroy|corduroys)\M' then
    mother := 'bottoms'; raw_category := 'corduroy-pants'; tags := tags || array['corduroy-pants', 'pants', 'bottoms']; evidence_parts := evidence_parts || array['product signal: corduroy pants'];
  elsif signal ~ '\m(overall|overalls|shortall|shortalls)\M' then
    mother := 'jumpsuits-rompers'; raw_category := 'overalls'; tags := tags || array['overalls']; evidence_parts := evidence_parts || array['product signal: overalls/shortalls'];
  elsif signal ~ '\m(coverall|coveralls|catsuit|catsuits|snowsuit|snowsuits)\M' then
    mother := 'jumpsuits-rompers'; raw_category := 'coveralls'; tags := tags || array['coveralls']; evidence_parts := evidence_parts || array['product signal: coveralls/catsuit/snowsuit'];
  elsif signal ~ '\m(romper|rompers)\M' then
    mother := 'jumpsuits-rompers'; raw_category := 'romper'; tags := tags || array['romper']; evidence_parts := evidence_parts || array['product signal: romper'];
  elsif signal ~ '\m(jumpsuit|jumpsuits)\M' then
    mother := 'jumpsuits-rompers'; raw_category := 'jumpsuit'; tags := tags || array['jumpsuit']; evidence_parts := evidence_parts || array['product signal: jumpsuit'];
  elsif signal ~ '\m(jean|jeans|denim)\M' then
    mother := 'bottoms'; raw_category := 'jeans'; tags := tags || array['jeans', 'pants', 'bottoms']; evidence_parts := evidence_parts || array['product signal: jeans/denim'];
  elsif signal ~ '\m(pant|pants|trouser|trousers|slack|slacks|flare|flares|bell|bells)\M' then
    mother := 'bottoms'; raw_category := 'pants'; tags := tags || array['pants', 'bottoms']; evidence_parts := evidence_parts || array['product signal: pants/trousers'];
  elsif signal ~ '\m(legging|leggings|tight|tights)\M' then
    mother := 'bottoms'; raw_category := 'leggings'; tags := tags || array['leggings', 'bottoms']; evidence_parts := evidence_parts || array['product signal: leggings'];
  elsif signal ~ '\m(short|shorts)\M' then
    mother := 'bottoms'; raw_category := 'shorts'; tags := tags || array['shorts', 'bottoms']; evidence_parts := evidence_parts || array['product signal: shorts'];
  elsif signal ~ '\m(skirt|skirts)\M' then
    mother := 'bottoms'; raw_category := 'skirt'; tags := tags || array['skirt', 'bottoms']; evidence_parts := evidence_parts || array['product signal: skirt'];
  elsif signal ~ '\m(caftan|caftans|kaftan|kaftans)\M' then
    mother := 'dresses'; raw_category := 'caftan'; tags := tags || array['caftan', 'dress']; evidence_parts := evidence_parts || array['product signal: caftan'];
  elsif signal ~ '\m(shirtdress|shirtdresses)\M' then
    mother := 'dresses'; raw_category := 'dress'; tags := tags || array['dress', 'dresses']; evidence_parts := evidence_parts || array['product signal: shirtdress'];
  elsif signal ~ '\m(gown|gowns|bridesmaid|formal|evening)\M' then
    mother := 'dresses'; raw_category := 'gown'; tags := tags || array['gown', 'dress', 'dresses']; evidence_parts := evidence_parts || array['product signal: gown/formal'];
  elsif signal ~ '\m(athletic dress|exercise dress|tennis dress)\M' then
    mother := 'activewear'; raw_category := 'athletic-dress'; tags := tags || array['athletic-dress', 'dress']; evidence_parts := evidence_parts || array['product signal: athletic dress'];
  elsif signal ~ '\m(dress|dresses|sundress)\M' then
    mother := 'dresses'; raw_category := 'dress'; tags := tags || array['dress', 'dresses']; evidence_parts := evidence_parts || array['product signal: dress'];
  elsif signal ~ '\m(bodysuit|bodysuits)\M' then
    mother := 'bodysuits'; raw_category := 'bodysuit'; tags := tags || array['bodysuit']; evidence_parts := evidence_parts || array['product signal: bodysuit'];
  elsif signal ~ '\m(bikini|bikinis)\M' then
    mother := 'swimwear'; raw_category := 'bikini'; tags := tags || array['bikini', 'swimwear']; evidence_parts := evidence_parts || array['product signal: bikini'];
  elsif signal ~ '\m(swim|swimsuit|swimwear)\M' then
    mother := 'swimwear'; raw_category := 'swimwear'; tags := tags || array['one-piece-swimsuit', 'swimwear']; evidence_parts := evidence_parts || array['product signal: swimwear'];
  elsif signal ~ '\m(jacket|jackets|blazer|blazers|shacket)\M' then
    mother := 'outerwear'; raw_category := 'jacket'; tags := tags || array['jacket']; evidence_parts := evidence_parts || array['product signal: jacket/blazer'];
  elsif signal ~ '\m(coat|coats|parka|trench)\M' then
    mother := 'outerwear'; raw_category := 'coat'; tags := tags || array['coat']; evidence_parts := evidence_parts || array['product signal: coat'];
  elsif signal ~ '\m(sports bra|sport bra)\M' then
    mother := 'activewear'; raw_category := 'sports-bra'; tags := tags || array['sports-bra', 'bra']; evidence_parts := evidence_parts || array['product signal: sports bra'];
  elsif signal ~ '\m(bustier|bustiers|corset|corsets|bandeau|bandeaus)\M' then
    mother := 'tops'; raw_category := 'bustier'; tags := tags || array['bustier', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: bustier/corset/bandeau'];
  elsif signal ~ '\m(bra|bras|bralette|bralettes)\M' then
    mother := 'intimates'; raw_category := 'bra'; tags := tags || array['bra']; evidence_parts := evidence_parts || array['product signal: bra'];
  elsif signal ~ '\m(underwear|panty|panties|brief|briefs|thong|thongs)\M' then
    mother := 'intimates'; raw_category := 'underwear'; tags := tags || array['underwear']; evidence_parts := evidence_parts || array['product signal: underwear'];
  elsif signal ~ '\m(pajama|pajamas|sleep|sleepwear)\M' then
    mother := 'sleepwear'; raw_category := 'pajamas'; tags := tags || array['pajamas']; evidence_parts := evidence_parts || array['product signal: pajamas/sleepwear'];
  elsif signal ~ '\m(leisure suit|suit|suits)\M' then
    mother := 'sets'; raw_category := 'suit'; tags := tags || array['suit', 'sets']; evidence_parts := evidence_parts || array['product signal: suit'];
  elsif signal ~ '\m(set|sets)\M' then
    mother := 'sets'; raw_category := 'sets'; tags := tags || array['sets']; evidence_parts := evidence_parts || array['product signal: set'];
  elsif signal ~ '\m(vest|vests)\M' then
    mother := 'tops'; raw_category := 'vest'; tags := tags || array['vest', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: vest'];
  elsif signal ~ '\m(sweatshirt|sweatshirts|hoodie|hoodies)\M' then
    mother := 'tops'; raw_category := 'sweatshirt'; tags := tags || array['sweatshirt', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: sweatshirt/hoodie'];
  elsif signal ~ '\m(tunic|tunics)\M' then
    mother := 'tops'; raw_category := 'tunic'; tags := tags || array['tunic', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: tunic'];
  elsif signal ~ '\m(button up|buttonup|button down|buttondown)\M' then
    mother := 'tops'; raw_category := 'button-up'; tags := tags || array['button-up', 'shirt', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: button-up shirt'];
  elsif signal ~ '\m(halter|halters)\M' then
    mother := 'tops'; raw_category := 'halter'; tags := tags || array['halter', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: halter'];
  elsif signal ~ '\m(blouse|blouses)\M' then
    mother := 'tops'; raw_category := 'blouse'; tags := tags || array['blouse', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: blouse'];
  elsif signal ~ '\m(shirt|shirts)\M' then
    mother := 'tops'; raw_category := 'shirt'; tags := tags || array['shirt', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: shirt'];
  elsif signal ~ '\m(tee|tees|t shirt|tshirt)\M' then
    mother := 'tops'; raw_category := 'tee'; tags := tags || array['tee', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: tee'];
  elsif signal ~ '\m(tank|cami|camisole)\M' then
    mother := 'tops'; raw_category := 'tank'; tags := tags || array['tank', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: tank/cami'];
  elsif signal ~ '\m(cardigan|cardigans)\M' then
    mother := 'tops'; raw_category := 'cardigan'; tags := tags || array['cardigan', 'sweater', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: cardigan'];
  elsif signal ~ '\m(sweater|sweaters|pullover)\M' then
    mother := 'tops'; raw_category := 'sweater'; tags := tags || array['sweater', 'top', 'tops']; evidence_parts := evidence_parts || array['product signal: sweater'];
  elsif signal ~ '\m(top|tops)\M' or signal ~ '[a-z]top\M' then
    mother := 'tops'; raw_category := 'top'; tags := tags || array['top', 'tops']; evidence_parts := evidence_parts || array['product signal: top'];
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
    raw_category := coalesce(raw_category, fallback_tag);
  end if;

  if mother is null and fallback_mother is not null then
    mother := fallback_mother;
  end if;

  if mother is null then
    evidence_parts := evidence_parts || array['needs taxonomy review: no descriptive product signal yet'];
  end if;

  select coalesce(array_agg(distinct tag_id order by tag_id), '{}'::text[])
  into tags
  from unnest(tags) as tag_id
  join staging.clothing_type_tags ct on ct.id = tag_id
  where tag_id <> 'other';

  if mother is null then
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
    raw_category,
    confidence,
    array_to_string(evidence_parts, '; '),
    mother is null
      or confidence = 'low'
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
      (array_remove(array_agg(brand order by created_at_display desc), null::text))[1] as observed_brand,
      coalesce(array_agg(distinct clothing_type_id) filter (where clothing_type_id is not null), '{}'::text[]) as observed_clothing_type_ids,
      count(*)::integer as image_row_count,
      min(created_at_display) as first_seen_at,
      max(created_at_display) as last_seen_at
    from source_images
    group by normalized_product_page_url
  ),
  enriched as (
    select
      pr.*,
      staging.infer_product_title_from_url(pr.normalized_product_page_url) as inferred_title,
      staging.infer_brand_from_product_url(pr.normalized_product_page_url) as inferred_brand
    from product_rollup pr
  ),
  classified as (
    select
      e.*,
      c.mother_category_id,
      c.clothing_type_tag_ids,
      c.product_category_raw,
      c.category_confidence,
      c.category_evidence,
      c.needs_manual_review
    from enriched e
    cross join lateral staging.category_from_product_signal(
      e.normalized_product_page_url,
      e.observed_clothing_type_ids,
      e.inferred_title
    ) c
  ),
  inserted as (
    insert into staging.product_pages (
      normalized_product_page_url,
      source_site,
      brand,
      product_title_raw,
      product_category_raw,
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
      coalesce(source_site, inferred_brand) as source_site,
      coalesce(observed_brand, inferred_brand) as brand,
      inferred_title as product_title_raw,
      product_category_raw,
      mother_category_id,
      category_confidence,
      category_evidence,
      needs_manual_review,
      observed_clothing_type_ids,
      image_row_count,
      first_seen_at,
      last_seen_at,
      jsonb_build_object(
        'staging_source', 'public.images distinct product links',
        'title_source', case when inferred_title is null then null else 'url_slug' end,
        'brand_source', case when observed_brand is not null then 'public.images.brand' else 'url_or_designer_path' end
      ),
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
    pp.observed_clothing_type_ids,
    pp.product_title_raw
  ) c
  cross join lateral unnest(c.clothing_type_tag_ids) as tag_id
  where tag_id <> 'other'
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

select * from staging.refresh_product_category_staging();
