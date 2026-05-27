# Sovrn Commerce Scraping Triage Plan

Source report: `/Users/briannasinger/Downloads/ab96212b-a1fd-48f3-adb6-76cbac7a5deb.csv`

Working triage tracker: `data-pipelines/non-amazon/docs/sovrn_commerce_apparel_triage_tracker.csv`

Original generated candidate queue: `/Users/briannasinger/Documents/Codex/2026-05-26/files-mentioned-by-the-user-ab96212b/sovereign-commerce-apparel-triage-candidates.csv`

## What The Report Contains

- 67,994 merchant rows.
- 48,518 unique merchant groups.
- Rows are affiliate merchant entries with merchant group, domains, supported geos, unsupported traffic types, pricing type, CPC, conversion rate, commission rate, order value, and network commission rates.
- The report does not include product categories or review metadata, so apparel fit relevance and customer-photo review support must be checked against the merchant websites.

## Triage Goal

Find e-commerce merchants that sell women's clothing or closely related fit-dependent apparel where sizing materially affects purchase confidence, then determine whether product reviews include customer-uploaded photos.

## Size-Important Scope

Include merchants when the site sells women's or mixed-gender products in categories where body fit matters:

- Tops, shirts, blouses, sweaters, jackets, coats.
- Dresses, skirts, pants, jeans, leggings, shorts.
- Bras, underwear, lingerie, shapewear, swimwear.
- Activewear, athleisure, outdoor apparel, uniforms, scrubs.

Exclude or deprioritize:

- Shoes, boots, and footwear merchants are out of scope for now.
- Accessory-only merchants: hats, jewelry, watches, bags, sunglasses, scarves, belts.
- Sites where size is incidental or one-size-only.
- Non-commerce sites, services, content sites, travel, finance, food, health products, and electronics.
- Brand collisions where an apparel brand name appears in a non-apparel merchant, such as branded wine, headphones, phone cases, portraits, or fitness equipment.

## Updated Priority Buckets

Use these statuses in the scraping triage plan:

- `P1 target_womens_fit_apparel_candidate`: known apparel, swim, intimates, department-store, or activewear merchant. Start here.
- `P1 marketplace_category_level_check`: broad marketplace or mass merchant that should be evaluated only at women's category and PDP level.
- `P2 target_womens_fit_apparel_candidate`: keyword-matched apparel candidate from merchant name or domain. Needs faster confirmation but likely relevant.
- `P3 needs_category_confirmation`: fashion, boutique, or women's signal exists, but product category evidence is not strong enough yet.
- `P4 exclude_accessory_or_low_size_importance`: accessory-only or low-fit-importance signal. Keep for audit, but do not scrape unless scope changes.

The generated candidate CSV currently has:

- `P1`: 79 high-confidence merchants, including 7 marketplace/category-level checks.
- `P2`: 540 keyword-matched fit-apparel candidates.
- `P3`: 92 category-confirmation candidates.
- `P4`: 301 accessory or low-size-importance exclusions.

## Verification Workflow

For each `P1` and `P2` merchant:

1. Normalize the primary domain.
2. Open the homepage and navigation.
3. Look for women's category paths such as `/women`, `/womens`, `/collections/women`, `/category/women`, `/clothing`, `/dresses`, `/tops`, `/swim`, `/lingerie`, or `/activewear`.
4. Capture one category evidence URL.
5. Sample 3 to 5 product detail pages from fit-dependent categories.
6. Mark `size_importance = yes` only if product pages show size variants, size charts, fit notes, model measurements, numeric/alpha sizes, or width/length/inseam options.
7. Mark `size_importance = no` for one-size products, accessory-only products, or products where size is not a meaningful selection.
8. Record which countries or shipping geos the website appears to support, using merchant-level Sovrn geos, storefront locale/domain, and public shipping-policy evidence.
9. Mark `shipping_geo_status = unknown` when the site does not expose clear public evidence; do not infer shipping countries from vague "international shipping" copy without a country list.
10. Check whether reviews exist on sampled product pages.
11. Check whether review content supports customer photos.
12. Record review provider, evidence URL, scrape feasibility, shipping geo evidence, and whether shipping availability should be inherited by product URLs during product-page staging.

Shipping geo verification should be lightweight and conservative. Do not use checkout automation, login-gated pages, private endpoints, address entry, or anti-bot workarounds to prove shipping coverage. If a product URL is country-specific, record both the merchant-level shipping evidence and the product/storefront market so the later product URL schema can populate `primary_market_country`, `shipping_geo_status`, and `product_page_shipping_geos`.

## Review Photo Detection

A merchant should be marked `photo_reviews = yes` when product pages show customer-uploaded photo thumbnails, review media galleries, or review API responses that contain user image URLs.

Check in this order:

1. Visible PDP review section: look for "customer photos", "reviews with photos", media thumbnails, gallery filters, or photo icons.
2. Embedded structured data: inspect JSON-LD and inline scripts for review/media fields.
3. Review widget providers:
   - Bazaarvoice
   - PowerReviews
   - Yotpo
   - Okendo
   - Judge.me
   - Loox
   - Stamped
   - Reviews.io
   - TurnTo
   - Shopify review apps
4. Network/API calls for review endpoints and media fields.
5. If reviews exist but sampled products have no photos, mark `photo_reviews = unknown_sample_too_small` unless the provider or UI clearly lacks photo support.

Use these values:

- `reviews_present`: `yes`, `no`, `unknown`.
- `photo_reviews`: `yes`, `no`, `unknown`, `unknown_sample_too_small`.
- `review_provider`: provider name or `native`, `none`, `unknown`.
- `review_photo_evidence`: PDP URL, review API URL, or short note about the visible UI.

## Scraping Triage Columns

Add or maintain these columns in the scraping triage tracker:

- `merchant_group_id`
- `merchant_group`
- `primary_domain`
- `priority`
- `triage_bucket`
- `pricing`
- `category_evidence_url`
- `sample_pdp_urls`
- `size_importance`
- `size_basis`
- `reviews_present`
- `photo_reviews`
- `review_provider`
- `review_photo_evidence`
- `ships_to_country_codes`
- `shipping_geo_status`
- `shipping_geo_evidence_url`
- `shipping_geo_evidence_basis`
- `primary_market_country`
- `product_url_geo_inheritance`
- `scrape_feasibility`
- `anti_bot_or_login_notes`
- `next_action`
- `checked_at`

Suggested values:

- `ships_to_country_codes`: pipe-delimited ISO 3166-1 alpha-2 country codes, such as `US|CA|GB`; blank when unknown.
- `shipping_geo_status`: `known_country_list`, `merchant_geo_only`, `market_specific_url`, `unknown`, or `needs_manual_review`.
- `shipping_geo_evidence_basis`: `sovrn_supported_geos`, `shipping_policy`, `storefront_locale`, `product_page_locale`, or `manual_note`.
- `primary_market_country`: the best-known market for the sampled product URLs, such as `US`, `CA`, `GB`, or blank when not clear.
- `product_url_geo_inheritance`: `merchant_level_ok`, `product_level_required`, or `unknown`.

## Execution Plan

1. Start with `P1` rows from the generated candidate queue.
2. Confirm 10 merchants manually to calibrate the rules and reduce false positives.
3. Build a lightweight crawler that visits homepage, category pages, and sampled PDPs.
4. Detect category evidence and size variants before doing review-photo checks.
5. Run the crawler over all `P1`, then `P2`.
6. Send `P3` rows through only the category-confirmation step.
7. Leave `P4` rows out of scraping unless manually promoted.
8. Review results for brand collisions and marketplaces.
9. Promote confirmed merchants into the main scraping queue.
10. For confirmed merchants without photo reviews, decide whether they are still worth scraping for product/size data alone.

Implementation output should be a completed triage tracker first, not raw review scrape output. Confirmed merchants can then be promoted into the normal non-Amazon scrape queue with claims, scripts, raw review rows, and summary JSONs.

## First Calibration Batch

Use the `calibration_batch_order` column in the working tracker for the first manual or semi-automated pass:

Calibration batch file: `data-pipelines/non-amazon/docs/sovrn_commerce_calibration_batch.csv`

1. Alo Yoga
2. Anthropologie
3. ASOS
4. Banana Republic
5. boohoo
6. Chico's
7. Everlane
8. Express Clothing
9. H&M
10. J. Crew

This batch intentionally skips broad marketplaces and footwear-first merchants so the initial rules can be calibrated against direct apparel retailers before handling more complex mixed-category sites.

## Special Handling

- Marketplaces and department stores such as Amazon, Walmart, eBay, Macy's, Nordstrom, Bloomingdale's, Kohl's, and JCPenney should be checked at category/PDP level, not merchant-wide, because they sell many non-target categories.
- International domains should be grouped under the same merchant when the site structure and review provider are shared, but shipping and storefront availability should still be tracked separately by country/market.
- Shopify stores are good candidates for automated review-provider detection because review app scripts and product JSON are often discoverable.
- Anti-bot-heavy merchants should be flagged rather than forced through the normal crawler.

## Immediate Next Queue

Begin with broad category-level checks for Amazon, Walmart, eBay, Target, Etsy, Temu, and AliExpress, then high-confidence `P1` merchants such as Alo Yoga, Anthropologie, ASOS, Athleta, Banana Republic, Bloomingdale's, Chico's, Everlane, Express Clothing, Free People, H&M, J.Crew, Lane Bryant, LOFT, lululemon, Madewell, Nordstrom, Old Navy, PrettyLittleThing, Princess Polly, Quince, Revolve, Saks, SHEIN, Shopbop, SKIMS, Spanx, Torrid, Uniqlo, Under Armour, Venus, Vuori, and White House Black Market.
