-- Add affiliate link resolution columns to staging.product_pages.
--
-- These columns store the result of the per-product-page affiliate network
-- selection (Amazon Associates, AWIN, Sovrn JS SDK, or none). Storing on
-- product_pages rather than images means one update per domain change instead
-- of N updates across all image rows for that page.
--
-- affiliate_network values:
--   amazon_associates  pre-generated ?tag= URL stored in affiliate_url
--   awin               AWIN tracking URL stored in affiliate_url (after generation)
--   sovrn_js           JS SDK rewrites at click time; affiliate_url is null
--   null               no affiliate program found yet

alter table staging.product_pages
  add column if not exists affiliate_network          text,
  add column if not exists affiliate_url              text,
  add column if not exists affiliate_url_fallback     text,
  add column if not exists affiliate_network_fallback text,
  add column if not exists affiliate_resolved_at      timestamptz;
