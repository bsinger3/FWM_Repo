# Product Category Tags Plan

## Goal

Move from a single `clothing_type_id` on each review/image row to a product-level category model that supports both:

- one frontend-facing mother category
- many searchable clothing type tags

For example:

- A pair of jeans should appear under `bottoms`, `pants`, and `jeans`.
- A blouse should appear under `tops`, `top`, and `blouse`.
- A jacket should appear under `outerwear`, `jacket`, and possibly `top`.

This is a planning document only. Do not implement this while other active pipeline or schema work is in flight.

## Current Staging Implementation

As of 2026-05-20, the first implementation step is intentionally backend-only:

- New objects live in the private `staging` schema, not in the live frontend query path.
- The website still uses `public.images`, `public.clothing_types`, and the existing `public.match_by_measurements` RPC.
- No frontend UI or search behavior changes are part of this staging step.
- No foreign key has been added from `public.images` to the staging product tables yet.
- Shipping countries/geos are not currently tracked on `staging.product_pages` or `public.images`.

Migration:

```text
supabase/migrations/20260520000000_add_product_category_staging.sql
```

The migration creates:

- `staging.clothing_mother_categories`
- `staging.clothing_type_tags`
- `staging.product_pages`
- `staging.product_page_clothing_type_tags`
- `staging.product_page_image_sources`
- `staging.normalize_product_url(raw_url text)`
- `staging.category_from_product_signal(normalized_product_page_url text, observed_clothing_type_ids text[])`
- `staging.refresh_product_category_staging()`
- `staging.sync_product_category_staging_from_images()`

`staging.refresh_product_category_staging()` can be rerun to rebuild staging product-page data from existing links in `public.images`. It uses `product_page_url_display` first and falls back to `monetized_product_url_display` when needed. Category assignment is based on URL slug signals plus existing `clothing_type_id` values as fallback evidence.

For routine updates, use `staging.sync_product_category_staging_from_images()` instead of the full refresh. It reads all normalized product links from `public.images`, upserts `staging.product_pages`, updates `staging.product_page_image_sources`, and updates auto-classified tag links while preserving product pages that have already been manually reviewed.

Standard procedure after every `public.images` load/update:

```sql
select *
from staging.sync_product_category_staging_from_images();
```

Then review the returned `auto_review_products` count. If it is non-zero, inspect only the newly/automatically flagged rows:

```sql
select
  id,
  normalized_product_page_url,
  product_title_raw,
  brand,
  mother_category_id,
  product_category_raw,
  observed_clothing_type_ids,
  category_confidence,
  category_evidence
from staging.product_pages
where (category_confidence = 'low' or needs_manual_review)
  and not (coalesce(raw_metadata, '{}'::jsonb) ? 'manual_reviewed_at')
order by updated_at desc;
```

Use `staging.refresh_product_category_staging()` only when deliberately rebuilding staging from scratch, because it truncates the staging product-page tables.

## Product Category Classification Procedure

Going forward, product categories should be generated from product-level evidence, not only from old image-level `clothing_type_id` values or URL slug matching.

For each normalized product URL in `staging.product_pages`:

1. Fetch the product page.
2. Extract the catalog/product photo URL from product-page metadata, preferring `og:image`, `twitter:image`, structured product JSON-LD image fields, or retailer-specific product image metadata.
3. Use the product title/name plus the catalog photo as the primary classification evidence.
4. Send both the catalog photo and the product title/name to a multimodal LLM.
5. Ask the LLM to return structured output only:

```json
{
  "mother_category_id": "tops",
  "product_category_raw": "blouse",
  "tag_ids": ["blouse", "tops"],
  "confidence": "high",
  "evidence": "Catalog photo shows a blouse; product title includes blouse.",
  "needs_manual_review": false
}
```

Classifier rules:

- The LLM must choose only taxonomy IDs that exist in `staging.clothing_mother_categories` and `staging.clothing_type_tags`, unless it explicitly flags that a new tag is needed.
- Tag suggestions must agree with the selected mother category. Do not mix unrelated tags such as `dress` and `jeans`.
- `other` should not be emitted as a garment category. If the product is a real garment and the taxonomy is missing the right category, create or propose a descriptive tag.
- If the catalog photo is unavailable, blocked, or clearly not a product image, fall back to product title/name and URL evidence, lower confidence, and set `needs_manual_review = true`.
- If the product page is unavailable or redirects to a no-product page, classify it as `source-review` and do not assign a frontend garment category.
- LLM outputs should be written to staging metadata and approval fields only. They should not affect the live frontend until the approval workbook has been reviewed and a production cutover migration is explicitly approved.

Recommended staging metadata fields for the LLM classifier:

- `catalog_photo_url`
- `catalog_photo_fetched_at`
- `catalog_photo_fetch_status`
- `llm_model`
- `llm_classified_at`
- `llm_mother_category_id`
- `llm_product_category_raw`
- `llm_tag_ids`
- `llm_confidence`
- `llm_evidence`
- `llm_needs_manual_review`

The approval workbook should include the catalog photo and at least one reviewer/customer photo side by side so the reviewer can validate that the product URL, catalog photo, product name, category, and tags all agree.

Quality notes from the first staging QA pass:

- Do not use `other` as a clothing category. If a product signal reveals a real garment type, add the missing category/tag instead.
- Product pages that are unavailable or cannot be identified should be staged under `source-review`, not `other`.
- `source-review` is not a frontend category and should not be exposed in the future clothing search UI.
- `product_title_raw`, `brand`, and `product_category_raw` should be populated whenever possible from existing image rows, URL slugs, or fetched product-page metadata.

## Recommended Category Model

Use one mother category for the UI and multiple tags for search matching.

Suggested mother categories:

- `tops`
- `bottoms`
- `dresses`
- `bodysuits`
- `swimwear`
- `outerwear`
- `intimates`
- `sets`
- `other`

Suggested searchable tags can be more granular:

- `jeans`
- `pants`
- `trousers`
- `leggings`
- `shorts`
- `skirt`
- `top`
- `blouse`
- `shirt`
- `tee`
- `tank`
- `sweater`
- `jacket`
- `coat`
- `dress`
- `gown`
- `bodysuit`
- `one-piece-swimsuit`
- `bikini`
- `bra`
- `underwear`

## Product-Level Storage

Scrape and enrich product metadata once per unique product page URL, then store the result in a separate product-level table.

Recommended tables:

- `public.product_pages`
  - one row per normalized product URL
  - stores source site, brand, product title, product category, raw metadata, mother category, confidence, evidence, manual-review status, and shipping/geo summary fields

- `public.product_page_shipping_geos`
  - many-to-many join table
  - connects one product page to one or more country/market codes when shipping or storefront availability has been verified

- `public.product_page_clothing_type_tags`
  - many-to-many join table
  - connects one product page to many `public.clothing_types` tags

- `public.images`
  - remains review/image-level
  - gets a `product_page_id` foreign key
  - can also keep a denormalized `mother_category_id` for simpler filtering

Keep the current `images.clothing_type_id` during migration for backwards compatibility, but stop treating it as the canonical category field once the new structure is live.

## Product Shipping Geo Tracking

Track product shipping/availability at the product URL level, not the review/image row level. One product can be visible in several country storefronts, and a single review image can be reused across locales.

Recommended fields on `public.product_pages`:

- `primary_market_country`: best-known storefront country for the normalized URL, using ISO 3166-1 alpha-2 codes such as `US`, `CA`, `GB`, or `AU`.
- `shipping_geo_status`: one of `unknown`, `ships_to_known_countries`, `does_not_ship_to_target_country`, `market_specific_url`, `needs_manual_review`.
- `shipping_geo_evidence`: short text note with the evidence source.
- `shipping_geo_checked_at`: timestamp for the last check.

Recommended table for normalized country/market coverage:

```sql
create table public.product_page_shipping_geos (
  product_page_id uuid references public.product_pages(id) on delete cascade,
  country_code text not null,
  availability_status text not null
    check (availability_status in (
      'ships_to',
      'does_not_ship_to',
      'available_in_market',
      'not_available_in_market',
      'unknown'
    )),
  evidence_url text,
  evidence_source text,
  checked_at timestamptz not null default now(),
  notes text,
  primary key (product_page_id, country_code)
);
```

Use `country_code` for the shopper destination or storefront market, not reviewer location. Reviewer location is a different concept and should stay separate if collected later.

Evidence should be gathered conservatively:

1. Merchant-level affiliate or Sovrn report geos when available.
2. Storefront locale/domain, such as `.com`, `.ca`, `.co.uk`, `/en-us`, or `/en-au`.
3. Public shipping policy pages when they clearly list destination countries.
4. Product page or cart UI only when it can be checked without login, checkout automation, address entry, or bypassing anti-bot systems.
5. Manual review notes for ambiguous cases.

Do not treat a country storefront URL as proof that every product ships to that country unless the product page is available in that storefront or the shipping policy clearly covers it. For international domains, group products under the same merchant only when the site structure and review provider are shared, but keep country availability rows separate.

## 1. Get Category Information From Product URLs

For each unique `product_page_url_display`, normalize the URL and classify the product using this priority order:

1. Product page structured metadata
   - Shopify product JSON
   - product title
   - product type/category
   - tags
   - description
   - breadcrumbs, when available
2. Product URL slug
3. Existing `clothing_type_id`
4. Manual review fallback

Do not use review text as the primary category source. Review text often mentions comparison garments, styling ideas, or other products.

Create a product enrichment output keyed by normalized product URL:

```csv
normalized_product_page_url,source_site,brand,product_title_raw,product_category_raw,mother_category_id,clothing_type_tag_ids,category_confidence,category_evidence,needs_manual_review,classified_at
```

Example:

```csv
https://example.com/products/high-rise-jean,example.com,Example Brand,High Rise Jean,Denim,bottoms,"jeans|pants|bottoms",high,"title: high rise jean; product_type: denim",false,2026-05-14T00:00:00Z
```

The classifier should emit:

- `mother_category_id`: exactly one value
- `clothing_type_tag_ids`: one or more values
- `category_confidence`: `high`, `medium`, or `low`
- `category_evidence`: short explanation of why the category was assigned
- `needs_manual_review`: true when confidence is low or metadata conflicts

## 2. Update Existing Repository And S3 Data

For existing CSVs in `FWM_Data`:

1. Collect all unique `product_page_url_display` values.
2. Normalize product URLs.
3. Scrape or enrich each unique product URL once.
4. Save a product-level enrichment file.
5. Join product enrichment back onto review/image CSV rows.
6. Add new columns:
   - `product_page_id` or `normalized_product_page_url`
   - `mother_category_id`
   - `clothing_type_tag_ids`
   - `category_confidence`
   - `category_evidence`
7. Keep existing `clothing_type_id` unchanged during the transition.

For historical rows without product metadata:

- use enrichment results when the product URL is known
- otherwise use a conservative mapping from existing `clothing_type_id`
- otherwise set `mother_category_id = other`, tag as `other`, and mark for manual review

Update repository docs and scripts only after the schema direction is accepted:

- scrape scripts that currently emit `clothing_type_id`
- CSV validation rules
- intake docs and scrape rules
- image review prompts that reference `clothing_type_id`
- frontend search request params
- Supabase migrations and generated types

After any generated data changes in `FWM_Data`, sync the private S3 backup:

```bash
cd /Users/briannasinger/Projects/FWM_Repo
scripts/sync-data-to-s3.sh
```

Save a dated migration manifest, for example:

```text
FWM_Data/migration_manifests/clothing_type_tags_YYYY-MM-DD.md
```

The manifest should include:

- files changed
- row counts before and after
- number of unique product URLs enriched
- number of products needing manual review
- S3 sync timestamp

## 3. Update Supabase Schema

Add mother categories:

```sql
create table public.clothing_mother_categories (
  id text primary key,
  label text not null,
  sort_order integer not null default 999
);
```

Keep `public.clothing_types`, but treat it as searchable tags:

```sql
alter table public.clothing_types
  add column if not exists mother_category_id text
    references public.clothing_mother_categories(id),
  add column if not exists is_search_tag boolean not null default true,
  add column if not exists is_frontend_filter boolean not null default false;
```

Add product pages:

```sql
create table public.product_pages (
  id uuid primary key default gen_random_uuid(),
  normalized_product_page_url text unique not null,
  source_site text,
  brand text,
  product_title_raw text,
  product_category_raw text,
  mother_category_id text references public.clothing_mother_categories(id),
  category_confidence text,
  category_evidence text,
  needs_manual_review boolean not null default false,
  primary_market_country text,
  shipping_geo_status text not null default 'unknown',
  shipping_geo_evidence text,
  shipping_geo_checked_at timestamptz,
  classified_at timestamptz not null default now()
);
```

Add product shipping geos:

```sql
create table public.product_page_shipping_geos (
  product_page_id uuid references public.product_pages(id) on delete cascade,
  country_code text not null,
  availability_status text not null
    check (availability_status in (
      'ships_to',
      'does_not_ship_to',
      'available_in_market',
      'not_available_in_market',
      'unknown'
    )),
  evidence_url text,
  evidence_source text,
  checked_at timestamptz not null default now(),
  notes text,
  primary key (product_page_id, country_code)
);
```

Add product-to-tag mappings:

```sql
create table public.product_page_clothing_type_tags (
  product_page_id uuid references public.product_pages(id) on delete cascade,
  clothing_type_id text references public.clothing_types(id),
  primary key (product_page_id, clothing_type_id)
);
```

Link image rows to products:

```sql
alter table public.images
  add column if not exists product_page_id uuid references public.product_pages(id),
  add column if not exists mother_category_id text references public.clothing_mother_categories(id);
```

## Search RPC Change

Current search filters against a single value:

```sql
i.clothing_type_id = in_clothing_type_id
```

The new search should match either the mother category or any product tag:

```sql
in_category_id is null
or i.mother_category_id = in_category_id
or exists (
  select 1
  from public.product_page_clothing_type_tags pct
  where pct.product_page_id = i.product_page_id
    and pct.clothing_type_id = in_category_id
)
```

During migration, support both:

- old param: `in_clothing_type_id`
- new param: `in_category_or_tag_id`

After the frontend is migrated, rename the UI label from `Clothing Type` to `Category`.

## Frontend Search UX Direction

Preferred future experience: a hybrid combo box that supports both browsing and typing.

Do not implement this UI as part of the initial category/tag migration. The migration should only make the data model and search API compatible with this later frontend direction.

The combo box should behave like:

- When the user clicks into the field, show common mother categories and popular clothing types.
- When the user types, autocomplete against canonical clothing tags and aliases.
- Group suggestions by mother category so the list feels organized instead of like one long database dropdown.
- Let a selected mother category match all child product tags, while a selected granular tag narrows the result set.
- Send canonical category/tag IDs to the search API, not raw typed text.

Example grouped suggestions for `dress`:

```text
Dresses
  Dress
  Maxi dress
  Formal dress
  Gown

Sets
  Dress set
```

Example grouped suggestions for `jea`:

```text
Bottoms
  Jeans
  Wide-leg jeans
  Denim pants
```

To support this later UX, the taxonomy should include frontend-friendly metadata:

- `display_label`
- `frontend_sort_order`
- `is_frontend_filter`
- optional `search_boost` or popularity ranking
- aliases/synonyms, either as a column or separate alias table

The initial frontend migration can still be simpler: show mother categories only, using:

```sql
select id, label, sort_order
from public.clothing_mother_categories
order by sort_order;
```

When the user selects `bottoms`, results should include products tagged with `jeans`, `pants`, `trousers`, `shorts`, `skirts`, and `leggings`.

Once the combo box is built, its API/view should return both mother categories and clothing tags in one shape:

```text
result_type, id, display_label, mother_category_id, mother_category_label, aliases, sort_order, search_boost
```

The frontend can then render grouped typeahead suggestions without hard-coding taxonomy structure.

## Rollout Plan

1. Agree on the mother category list and tag taxonomy.
2. Add a taxonomy config file in the repo.
3. Add product URL normalization and product metadata enrichment.
4. Fetch catalog photos from product URLs and run catalog-photo-plus-title LLM category classification into staging.
5. Generate a product enrichment/approval workbook from staging.
6. Review low-confidence products and LLM-proposed new tags manually.
7. Add Supabase migration for product pages, mother categories, and product tag mappings.
8. Add shipping geo fields and `product_page_shipping_geos`, initially defaulting unknown.
9. Backfill Supabase product pages and tag mappings.
10. Backfill product shipping geos from merchant-level report data, storefront locale, public shipping-policy evidence, and manual review where needed.
11. Update `match_by_measurements` to filter by mother category or tag.
12. Decide whether frontend search should filter by shopper country/ship-to country; do not expose shipping filters until enough product URLs have verified geo data.
13. Update the frontend dropdown to use mother categories as the initial simple UI.
14. Keep `images.clothing_type_id` for one release.
15. Stop writing or relying on `images.clothing_type_id` after the new search path is stable.
16. Later, replace the simple dropdown with the grouped hybrid combo box/typeahead.

## Validation

Before cutover:

- Count rows with blank `mother_category_id`.
- Count products with zero tags.
- Count rows where LLM tag IDs do not belong to the selected mother category.
- Count rows where catalog photo extraction failed and verify they are either manually reviewed or explicitly low confidence.
- Sample at least 25 products per mother category.
- Confirm `jeans` appears under both `jeans` tag matching and `bottoms` category matching.
- Confirm bras/intimates do not disappear from search.
- Confirm legacy `in_clothing_type_id` behavior still works during the transition.
- Count product pages with `shipping_geo_status = 'unknown'`.
- For any future ship-to filter, confirm products without verified shipping data are handled intentionally rather than silently excluded.
- Sample at least 25 `product_page_shipping_geos` rows and verify the evidence source supports the country/market value.
- Confirm generated data changes have been synced to S3.
