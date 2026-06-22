-- Add the full source breadcrumb path to staging.product_pages.
--
-- Taxonomy promotion only stores the COLLAPSED category (mother_category_id +
-- clothing_type tags). The fine-grained breadcrumb leaves we scrape (e.g.
-- "Clothing, Shoes & Jewelry > Women > Clothing > Pants > Wear to Work") were
-- being discarded after classification. This column retains the raw,
-- fully-qualified breadcrumb path verbatim so we can facet on subcategories
-- later without a re-scrape.
--
-- Lossless and additive: nullable text, populated by the taxonomy promote step
-- from the captured breadcrumb signal. Independent of mother_category_id.

alter table staging.product_pages
  add column if not exists category_breadcrumb_path text;
