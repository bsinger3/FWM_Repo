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
  - stores source site, brand, product title, product category, raw metadata, mother category, confidence, evidence, and manual-review status

- `public.product_page_clothing_type_tags`
  - many-to-many join table
  - connects one product page to many `public.clothing_types` tags

- `public.images`
  - remains review/image-level
  - gets a `product_page_id` foreign key
  - can also keep a denormalized `mother_category_id` for simpler filtering

Keep the current `images.clothing_type_id` during migration for backwards compatibility, but stop treating it as the canonical category field once the new structure is live.

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
  classified_at timestamptz not null default now()
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

## Frontend Change

The frontend dropdown should show mother categories, not every granular clothing tag:

```sql
select id, label, sort_order
from public.clothing_mother_categories
order by sort_order;
```

When the user selects `bottoms`, results should include products tagged with `jeans`, `pants`, `trousers`, `shorts`, `skirts`, and `leggings`.

## Rollout Plan

1. Agree on the mother category list and tag taxonomy.
2. Add a taxonomy config file in the repo.
3. Add product URL normalization and product metadata enrichment.
4. Generate a product enrichment file from existing `FWM_Data`.
5. Review low-confidence products manually.
6. Add Supabase migration for product pages, mother categories, and product tag mappings.
7. Backfill Supabase product pages and tag mappings.
8. Update `match_by_measurements` to filter by mother category or tag.
9. Update the frontend dropdown to use mother categories.
10. Keep `images.clothing_type_id` for one release.
11. Stop writing or relying on `images.clothing_type_id` after the new search path is stable.

## Validation

Before cutover:

- Count rows with blank `mother_category_id`.
- Count products with zero tags.
- Sample at least 25 products per mother category.
- Confirm `jeans` appears under both `jeans` tag matching and `bottoms` category matching.
- Confirm bras/intimates do not disappear from search.
- Confirm legacy `in_clothing_type_id` behavior still works during the transition.
- Confirm generated data changes have been synced to S3.

