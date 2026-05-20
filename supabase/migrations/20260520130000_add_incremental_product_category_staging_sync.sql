-- Add the routine staging sync used after public.images is updated.
-- Unlike staging.refresh_product_category_staging(), this does not truncate staging
-- tables and preserves rows that have already been manually reviewed.

create or replace function staging.sync_product_category_staging_from_images()
returns table(
  product_pages_upserted integer,
  image_links_upserted integer,
  image_links_removed integer,
  tag_links_upserted integer,
  auto_review_products integer
)
language plpgsql
security definer
set search_path = staging, public, pg_temp
as $function$
declare
  product_count integer := 0;
  image_count integer := 0;
  removed_image_count integer := 0;
  tag_count integer := 0;
  review_count integer := 0;
begin
  create temporary table _staging_source_images on commit drop as
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
  ) is not null;

  create index on _staging_source_images (normalized_product_page_url);
  create index on _staging_source_images (image_id);

  create temporary table _staging_product_rollup on commit drop as
  with product_rollup as (
    select
      normalized_product_page_url,
      (array_remove(array_agg(source_site_display order by created_at_display desc), null::text))[1] as source_site,
      (array_remove(array_agg(brand order by created_at_display desc), null::text))[1] as observed_brand,
      coalesce(array_agg(distinct clothing_type_id) filter (where clothing_type_id is not null), '{}'::text[]) as observed_clothing_type_ids,
      count(*)::integer as image_row_count,
      min(created_at_display) as first_seen_at,
      max(created_at_display) as last_seen_at
    from _staging_source_images
    group by normalized_product_page_url
  ),
  enriched as (
    select
      pr.*,
      staging.infer_product_title_from_url(pr.normalized_product_page_url) as inferred_title,
      staging.infer_brand_from_product_url(pr.normalized_product_page_url) as inferred_brand
    from product_rollup pr
  )
  select
    e.normalized_product_page_url,
    coalesce(e.source_site, e.inferred_brand) as source_site,
    coalesce(e.observed_brand, e.inferred_brand) as brand,
    e.inferred_title as product_title_raw,
    c.product_category_raw,
    c.mother_category_id,
    c.category_confidence,
    c.category_evidence,
    c.needs_manual_review,
    e.observed_clothing_type_ids,
    e.image_row_count,
    e.first_seen_at,
    e.last_seen_at,
    c.clothing_type_tag_ids,
    jsonb_build_object(
      'staging_source', 'public.images distinct product links',
      'title_source', case when e.inferred_title is null then null else 'url_slug' end,
      'brand_source', case when e.observed_brand is not null then 'public.images.brand' else 'url_or_designer_path' end,
      'last_synced_from_images_at', now()
    ) as sync_metadata
  from enriched e
  cross join lateral staging.category_from_product_signal(
    e.normalized_product_page_url,
    e.observed_clothing_type_ids,
    e.inferred_title
  ) c;

  create index on _staging_product_rollup (normalized_product_page_url);

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
    sync_metadata,
    now(),
    now()
  from _staging_product_rollup
  on conflict (normalized_product_page_url) do update set
    source_site = excluded.source_site,
    brand = coalesce(staging.product_pages.brand, excluded.brand),
    product_title_raw = coalesce(staging.product_pages.product_title_raw, excluded.product_title_raw),
    product_category_raw = case
      when coalesce(staging.product_pages.raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at'
        then staging.product_pages.product_category_raw
      else excluded.product_category_raw
    end,
    mother_category_id = case
      when coalesce(staging.product_pages.raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at'
        then staging.product_pages.mother_category_id
      else excluded.mother_category_id
    end,
    category_confidence = case
      when coalesce(staging.product_pages.raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at'
        then staging.product_pages.category_confidence
      else excluded.category_confidence
    end,
    category_evidence = case
      when coalesce(staging.product_pages.raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at'
        then staging.product_pages.category_evidence
      else excluded.category_evidence
    end,
    needs_manual_review = case
      when coalesce(staging.product_pages.raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at'
        then staging.product_pages.needs_manual_review
      else excluded.needs_manual_review
    end,
    observed_clothing_type_ids = excluded.observed_clothing_type_ids,
    image_row_count = excluded.image_row_count,
    first_seen_at = excluded.first_seen_at,
    last_seen_at = excluded.last_seen_at,
    raw_metadata = coalesce(staging.product_pages.raw_metadata, '{}'::jsonb)
      || coalesce(excluded.raw_metadata, '{}'::jsonb),
    updated_at = now();

  get diagnostics product_count = row_count;

  delete from staging.product_page_image_sources pis
  using staging.product_pages pp
  where pis.product_page_id = pp.id
    and not exists (
      select 1
      from _staging_source_images si
      where si.image_id = pis.image_id
        and si.normalized_product_page_url = pp.normalized_product_page_url
    );

  get diagnostics removed_image_count = row_count;

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
  from _staging_source_images si
  join staging.product_pages pp
    on pp.normalized_product_page_url = si.normalized_product_page_url
  on conflict (product_page_id, image_id) do update set
    original_product_page_url = excluded.original_product_page_url,
    original_monetized_product_url = excluded.original_monetized_product_url,
    source_site = excluded.source_site,
    brand = excluded.brand,
    clothing_type_id = excluded.clothing_type_id,
    created_at_display = excluded.created_at_display;

  get diagnostics image_count = row_count;

  delete from staging.product_page_clothing_type_tags pt
  using staging.product_pages pp
  join _staging_product_rollup pr
    on pr.normalized_product_page_url = pp.normalized_product_page_url
  where pt.product_page_id = pp.id
    and not (coalesce(pp.raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at');

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
  join _staging_product_rollup pr
    on pr.normalized_product_page_url = pp.normalized_product_page_url
  cross join lateral unnest(pr.clothing_type_tag_ids) as tag_id
  where tag_id <> 'other'
    and not (coalesce(pp.raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at')
  on conflict (product_page_id, clothing_type_id) do update set
    evidence = excluded.evidence;

  get diagnostics tag_count = row_count;

  select count(*)::integer
  into review_count
  from staging.product_pages
  where (category_confidence = 'low' or needs_manual_review)
    and not (coalesce(raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at');

  product_pages_upserted := product_count;
  image_links_upserted := image_count;
  image_links_removed := removed_image_count;
  tag_links_upserted := tag_count;
  auto_review_products := review_count;
  return next;
end;
$function$;

grant execute on function staging.sync_product_category_staging_from_images() to service_role;
