# Products Table Data Pipeline

This directory is the working area for product-level data before it is promoted
into the eventual products table.

The products table should be keyed by the normalized product link: the purchase
page where a shopper can buy the item. Review/image rows can point to that
product, but category decisions should be made once at the product level.

## Why This Exists

The existing scrape pipeline captures review/image rows. That is still useful,
but product category metadata belongs in a separate product-level pass because:

- many review images can belong to the same product link
- product pages often expose better category evidence than review text
- website collection pages, filters, breadcrumbs, and sorting options are useful
  signals for tags like `mini-skirt`, `midi-skirt`, `wide-leg-pants`, or
  `long-pants`
- category determines which measurements matter for fit search and display

This directory should preserve the evidence trail from retailer taxonomy to our
canonical taxonomy.

## Directory Layout

- `taxonomy/`: canonical high-level categories, lower-level tags, aliases, and
  measurement profiles.
- `schemas/`: CSV contracts for source evidence and product records.
- `examples/`: small hand-authored examples showing the expected shapes.
- `work/`: local generated workbooks, raw inventories, and merchant-specific
  scratch outputs. Keep large generated files out of git unless they are a
  deliberate handoff artifact.

## Core Concepts

`product_link`
: Raw product purchase URL as seen in the scrape or website.

`normalized_product_link`
: Lowercased, query-stripped, fragment-stripped product URL. This is the unique
  identifier for the products table.

`mother_category_id`
: Exactly one high-level frontend category such as `tops`, `bottoms`,
  `dresses`, `skirts`, or `pants`.

`category_tag_ids`
: One or more lower-level descriptive tags. Tags can come from product metadata,
  collection pages, breadcrumbs, website filters, sort pages, product titles,
  and catalog photos.

`measurement_profile_id`
: The fit measurement bundle that should be associated with the product
  category, such as `upper_body`, `lower_body`, `full_body`, `bra`, or `swim`.

## Evidence Priority

Use product-level and website-level evidence before review text:

1. Product page structured data, product title, product type, and breadcrumbs.
2. Website collection/filter/sort pages where the retailer already categorizes
   products.
3. Product URL slug.
4. Catalog photo plus product title classification.
5. Existing trusted `clothing_type_id`.
6. Manual review.

Review text can help explain fit, but it should not be the primary category
source because customers often mention comparison garments or styling ideas.

## Merchant Workflow

For each merchant:

1. Inventory category URLs, collection URLs, filter options, and sorting metrics
   into `schemas/website_category_evidence.csv`.
2. Collect unique product links from raw scrape outputs, sitemaps, collection
   pages, product feeds, and review-provider data.
3. Normalize product links and generate one row per product using
   `schemas/product_records.csv`.
4. Join website category evidence onto products by product URL, collection URL,
   breadcrumb, product type, tag, or product listing page membership.
5. Assign exactly one `mother_category_id`, one `measurement_profile_id`, and
   one or more `category_tag_ids`.
6. Route conflicting or low-confidence rows to manual review rather than
   guessing.

## Promotion Rules

Before product rows are promoted into Supabase:

- `normalized_product_link` must be unique and non-empty.
- `product_link` must resolve to a buyable product page or be marked
  `source-review`.
- `mother_category_id` must be one known taxonomy ID.
- `category_tag_ids` must agree with the mother category.
- `measurement_profile_id` must be populated for every garment category.
- source evidence should name where the category came from.
- low-confidence or conflicting category evidence should be kept out of
  production until reviewed.

This pipeline complements the private staging tables described in
`product-category-tags-plan.md`; it does not change the live website by itself.
