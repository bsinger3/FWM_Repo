-- Dev-only explicit robots flag for product-page availability audits.

do $$
begin
  if to_regclass('staging.product_pages') is null then
    raise exception 'staging.product_pages is required before applying dev product-page robots flag';
  end if;
end;
$$;

alter table staging.product_pages
  add column if not exists robots_disallowed boolean;

comment on column staging.product_pages.robots_disallowed is
  'DEV ONLY boolean set by product-page status audit when robots.txt disallows fetching the page for the configured audit user agent.';

create index if not exists product_pages_robots_disallowed_idx
  on staging.product_pages (robots_disallowed);
