-- Dev-only catalog image metadata for taxonomy approval.
-- Stores product-page catalog image URLs so review tooling does not have to
-- rediscover them on every dashboard load.

do $$
begin
  if to_regclass('staging.product_pages') is null then
    raise exception 'staging.product_pages is required before applying dev product-page catalog image support';
  end if;
end $$;

alter table staging.product_pages
  add column if not exists catalog_image_url text,
  add column if not exists catalog_image_urls text[] not null default '{}',
  add column if not exists catalog_image_source text,
  add column if not exists catalog_image_fetched_at timestamptz,
  add column if not exists catalog_image_fetch_status text,
  add column if not exists catalog_image_fetch_error text;

comment on column staging.product_pages.catalog_image_url is
  'DEV ONLY primary product/catalog image URL extracted from product-page metadata for taxonomy approval.';

comment on column staging.product_pages.catalog_image_urls is
  'DEV ONLY all product/catalog image URLs extracted from product-page metadata for taxonomy approval.';

comment on column staging.product_pages.catalog_image_source is
  'DEV ONLY source used for catalog_image_url, such as json_ld, meta, shopify_product_json, or amazon_browser.';

comment on column staging.product_pages.catalog_image_fetched_at is
  'DEV ONLY timestamp for the most recent catalog image extraction attempt.';

comment on column staging.product_pages.catalog_image_fetch_status is
  'DEV ONLY extraction status for product-page catalog images.';

comment on column staging.product_pages.catalog_image_fetch_error is
  'DEV ONLY error text from the most recent catalog image extraction attempt.';

create index if not exists product_pages_catalog_image_fetched_at_idx
  on staging.product_pages (catalog_image_fetched_at);
