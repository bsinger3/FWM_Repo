-- Dev-only product-page taxonomy enrichment support.
-- Keeps workbook clothing/category values as provenance while allowing
-- evidence-backed product-page item/material/style tags.

do $$
begin
  if to_regclass('staging.product_pages') is null then
    raise exception 'staging.product_pages is required before applying dev product-page taxonomy support';
  end if;
end $$;

alter table staging.product_pages
  add column if not exists category_source_field text,
  add column if not exists category_extractor_version text,
  add column if not exists category_checked_at timestamptz;

comment on column staging.product_pages.category_source_field is
  'DEV ONLY field naming the page source used for the primary broad category, such as json_ld, title, breadcrumb, description, url_slug, or workbook_fallback.';

comment on column staging.product_pages.category_extractor_version is
  'DEV ONLY taxonomy extractor version used for the current category fields.';

create table if not exists staging.product_page_attribute_tags (
  product_page_id uuid not null references staging.product_pages(id) on delete cascade,
  tag_type text not null,
  tag_id text not null,
  label text not null,
  confidence text not null default 'low'
    check (confidence in ('high', 'medium', 'low')),
  evidence text,
  source_field text,
  extractor_version text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (product_page_id, tag_type, tag_id)
);

comment on table staging.product_page_attribute_tags is
  'DEV ONLY richer product-page taxonomy tags such as material, style, fit, length, rise, pattern, and detail.';

create index if not exists product_page_attribute_tags_type_tag_idx
  on staging.product_page_attribute_tags (tag_type, tag_id);

create index if not exists product_page_attribute_tags_product_page_idx
  on staging.product_page_attribute_tags (product_page_id);

create index if not exists product_pages_category_extractor_version_idx
  on staging.product_pages (category_extractor_version);

grant select, insert, update, delete on staging.product_page_attribute_tags to service_role;
