# Required fields to capture at scrape time (for `staging.product_pages`)

**Why this exists:** In June 2026 we discovered ~4,498 Amazon product pages in
`staging.product_pages` had **no category** because the original scrape never
captured the taxonomy signals. Recovering them required a slow, throttled,
one-page-at-a-time HTTP backfill (`scripts/backfill-amazon-taxonomy-free.mjs`,
~days of wall-clock against Amazon rate limits). **Capturing the right fields
the first time avoids ever repeating that.**

Rule: **every scrape that produces a product page must capture the fields below
in the same pass**, while we already have the page HTML in hand. Do not defer
taxonomy to a later step — derive it at intake from the raw signals.

## 1. Columns that land in `staging.product_pages`

(authoritative list — see the SELECT in
`scripts/export-product-pages-working-copy.mjs`)

| Column | What to capture |
|---|---|
| `normalized_product_page_url` | Canonical product URL (strip tracking/`/ref=…?…`; for Amazon use `https://www.amazon.com/dp/{ASIN}`). |
| `source_site` | Merchant root (e.g. `https://www.amazon.com/`). |
| `brand` | Brand/manufacturer. |
| `product_title_raw` | The product title exactly as shown (Amazon: `#productTitle`). |
| `product_category_raw` | The merchant's own category label / breadcrumb leaf, verbatim. |
| `mother_category_id` | Derived taxonomy category — run the raw signals (§2) through `extractTaxonomy()` at intake. |
| `category_confidence` / `category_evidence` / `category_source_field` | Provenance from `extractTaxonomy()`. |
| `category_breadcrumb_path` | The **full** source breadcrumb path, verbatim (e.g. `Clothing, Shoes & Jewelry > Women > Clothing > Pants > Wear to Work`). Lossless — retains the fine-grained leaves that `mother_category_id` collapses away. |
| `category_extractor_version` | The extractor version string used. |
| `observed_clothing_type_ids` | Item-type tags from `extractTaxonomy()` (`itemTags[]`). |
| `source_status` | in_stock / out_of_stock / unavailable. |
| `robots_disallowed` | Whether robots.txt disallowed the fetched URL. |
| `first_seen_at` / `last_seen_at` | Timestamps. |

(`image_row_count`, `needs_manual_review`, `updated_at` are derived downstream.)

## 2. Raw taxonomy signals to capture (so category is derivable without a re-fetch)

These are the **inputs** to the shared classifier `extractTaxonomy()` in
`scripts/audit-dev-product-page-taxonomy.mjs`. Capture them per page and either
classify at intake or store them so a later pass can, without hitting the site
again:

- **title** — product title (Amazon `#productTitle`, else `<title>`/`og:title`).
- **breadcrumb** — wayfinding breadcrumb, joined `A > B > C`
  (Amazon `#wayfinding-breadcrumbs_feature_div`; else JSON-LD `BreadcrumbList`).
- **best sellers rank category** (Amazon) — e.g. `#5 in Women's Jeans` → `Women's Jeans`.
- **url_slug** — meaningful tokens from the product URL path.
- **json_ld_product_core / description** — JSON-LD `Product` name/category/description when present.

Feed these as the `fields` object into `extractTaxonomy(fields)` — do **not**
invent a parallel category mapping. The classifier returns
`primaryCategory{mother_category_id, category_confidence, category_evidence,
category_source_field}` + `itemTags[]`, which map 1:1 onto the columns in §1.

## 3. Practical checklist for a new scraper

- [ ] Capture all §1 columns + all §2 raw signals in the **same pass** as the rest of the page.
- [ ] Normalize the URL before storing (canonical, no tracking params).
- [ ] Derive taxonomy at intake via `extractTaxonomy()`; store category + evidence + extractor version.
- [ ] If a page yields no confident category, store it as `needs_manual_review` rather than dropping the signals — keep the raw title/breadcrumb so it can be re-classified offline (no re-scrape).

See also: `DATA.md` (data layout), `scripts/audit-dev-product-page-taxonomy.mjs`
(the classifier), and the backfill scripts
`scripts/build-amazon-taxonomy-worklist.mjs` /
`scripts/backfill-amazon-taxonomy-free.mjs` (the recovery path we want to avoid needing).
