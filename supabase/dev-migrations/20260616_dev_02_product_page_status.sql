-- Dev-only product-page availability metadata for the images table refresh.
-- Do not place this status-tracking schema in production migrations until the
-- audit workflow and frontend behavior are separately approved.

do $$
begin
  if to_regclass('staging.product_pages') is null then
    raise exception 'staging.product_pages is required before applying dev product-page status tracking';
  end if;
end;
$$;

alter table staging.product_pages
  add column if not exists source_status text,
  add column if not exists source_status_checked_at timestamptz,
  add column if not exists source_http_status integer,
  add column if not exists source_final_url text,
  add column if not exists source_redirected boolean,
  add column if not exists source_final_url_type text,
  add column if not exists source_status_evidence text,
  add column if not exists source_status_error text,
  add column if not exists source_status_checker_version text;

comment on column staging.product_pages.source_status is
  'DEV ONLY product-page availability status. Metadata first; do not hide baseline rows from search until reviewed.';

comment on column staging.product_pages.source_status_checker_version is
  'Version string set on every dev product-page status audit attempt.';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'product_pages_source_status_check'
      and conrelid = 'staging.product_pages'::regclass
  ) then
    alter table staging.product_pages
      add constraint product_pages_source_status_check
      check (
        source_status is null or source_status in (
          'live',
          'out_of_stock',
          'page_not_found',
          'product_unavailable',
          'blocked_or_forbidden',
          'robots_disallowed',
          'redirected_to_product',
          'redirected_to_non_product',
          'timeout',
          'unknown'
        )
      ) not valid;
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'product_pages_source_final_url_type_check'
      and conrelid = 'staging.product_pages'::regclass
  ) then
    alter table staging.product_pages
      add constraint product_pages_source_final_url_type_check
      check (
        source_final_url_type is null or source_final_url_type in (
          'product',
          'non_product',
          'blocked',
          'unknown'
        )
      ) not valid;
  end if;
end;
$$;

create index if not exists product_pages_source_status_idx
  on staging.product_pages (source_status);

create index if not exists product_pages_source_status_checked_at_idx
  on staging.product_pages (source_status_checked_at);

create index if not exists product_pages_source_status_checker_version_idx
  on staging.product_pages (source_status_checker_version);
