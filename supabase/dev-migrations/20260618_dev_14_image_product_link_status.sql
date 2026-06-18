-- Dev-only image-level product-link status mirror.
-- Keep this intentionally compact: one nullable status field copied from the
-- associated staging.product_pages row when the link is confirmed unusable.

alter table public.images
  add column if not exists product_link_status text;

comment on column public.images.product_link_status is
  'DEV ONLY nullable product-link status copied from staging.product_pages. Null means not known dead; values like page_not_found or redirected_to_non_product mean exclude from product-search surfaces.';

create index if not exists images_product_link_status_idx
  on public.images (product_link_status);
