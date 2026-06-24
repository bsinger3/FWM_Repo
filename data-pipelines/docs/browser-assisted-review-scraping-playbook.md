# Browser-Assisted Review Scraping Playbook

**Purpose:** Preserve the Levi breakthrough from 2026-06-24 as a reusable
workflow for retailers that looked blocked from normal command-line scraping.
Use this before writing off targets such as Lulus, Madewell, AE, or other sites
that return 403/captcha/WAF responses to `curl` or fresh Playwright sessions.

The goal is not to bypass a bot wall. The goal is to use a normal visible
browser briefly to identify public review-provider configuration, then build a
stable scraper against anonymous public pages or public third-party APIs.

## Guardrails

- Use public pages, public scripts, public sitemaps, and anonymous public review
  APIs only.
- Do not export or replay cookies, session headers, Akamai/PerimeterX challenge
  tokens, account state, cart state, or auth headers.
- Stop or back off on `401`, `403`, `407`, `423`, `429`, captcha, WAF,
  "Access Denied", or challenge markers unless a public third-party endpoint is
  independently discoverable from static assets.
- Prefer provider APIs with explicit public keys embedded in public scripts over
  brittle DOM scraping.
- For every scrape that emits product URLs, also emit product-page taxonomy
  signals in the same pass. See
  `data-pipelines/docs/scrape_required_fields_for_product_pages.md`.

## What Worked For Levi

Levi initially looked blocked:

- Direct PDP fetches returned Akamai `Access Denied`.
- Fresh headless/regular Playwright attempts also hit `Access Denied` or blank
  rendering.
- The in-app Chrome extension, using Bri's normal browser surface, could render
  the Levi PDP and its Bazaarvoice widget.

The useful observation was:

- Rendered PDPs contained `data-bv-product-id`, for example
  `188820023-US`.
- Rendered review pages injected `#bv-jsonld-reviews-data`, proving the
  review content and customer photo URLs existed in public widget data.
- The public Bazaarvoice deployment script was visible:
  `https://apps.bazaarvoice.com/deployments/levis/lsa_implementation_production/production/en_US/bv.js`
- That script pointed to the legacy public config:
  `https://display.ugc.bazaarvoice.com/static/levis/lsa_implementation_production/en_US/bvapi.js`
- `bvapi.js` exposed the anonymous public API details:
  - client: `levis`
  - display code: `18056_16_0-en_us`
  - API root: `https://api.bazaarvoice.com/data/`
  - passkey: public BV passkey embedded in the script

The final scraper did not need browser automation. It used:

```text
https://api.bazaarvoice.com/data/reviews.json
  ?passkey=...
  &apiversion=5.5
  &displaycode=18056_16_0-en_us
  &filter=productid:eq:{PRODUCT_ID}
  &filter=isratingsonly:eq:false
  &filter=hasphotos:eq:true
  &sort=submissiontime:desc
  &limit=100
  &offset=...
```

Key optimization: `filter=hasphotos:eq:true` avoided paging thousands of
text-only reviews.

Levi also exposed useful product metadata:

```text
https://api.bazaarvoice.com/data/products.json
  ?passkey=...
  &apiversion=5.5
  &displaycode=18056_16_0-en_us
  &filter=id:eq:{PRODUCT_ID}
  &stats=reviews
```

That endpoint provided review/photo counts, product name, catalog image URLs,
family IDs, attributes, and review-context distributions.

## Standard Workflow For A Blocked Retailer

1. **Start with a normal public check.**
   - Fetch `robots.txt`, public sitemaps, candidate category pages, and sample
     PDPs.
   - Record whether `curl` returns normal HTML, WAF/captcha, blank app shell,
     or static config.

2. **Open one high-value PDP in a visible browser.**
   - Use a product known to have image reviews if possible.
   - Scroll to the review section and trigger pagination/filter UI.
   - Observe provider names in scripts, iframes, DOM attributes, and image URLs.

3. **Capture public provider clues, not session state.**
   Look for:
   - Script URLs containing `bazaarvoice`, `bv`, `powerreviews`, `yotpo`,
     `okendo`, `loox`, `turnto`, `pixlee`, `reviews`, `ugc`, `ratings`.
   - DOM attributes such as `data-bv-product-id`, `data-bv-show`,
     `data-product-id`, `data-review-id`, `data-yotpo-product-id`.
   - JSON-LD review scripts such as `#bv-jsonld-reviews-data`.
   - Public iframe params such as `widget_id`, `product_id`, `api_key`.
   - Customer image URL hosts such as `photos-us.bazaarvoice.com`.

4. **Switch back to static/public endpoints if possible.**
   - Fetch public provider config scripts directly.
   - Search them for `passkey`, `apiKey`, `storeId`, `merchantId`,
     `displaycode`, `client`, `reviews.json`, `batch.json`, `products.json`,
     `hasphotos`, `media`, `photo`, `pagination`, `offset`, `limit`.
   - Test the smallest anonymous provider API call.

5. **Write the scraper against the public API, not the browser.**
   Browser automation should be the discovery tool, not the production data
   plane, unless no public API exists.

6. **Keep review rows and product-page sidecars together.**
   Every product URL in review output should have a product-page row or enough
   raw product metadata to generate one without another site fetch.

## Provider Recipes

### Bazaarvoice

Useful static files:

- `https://apps.bazaarvoice.com/deployments/{client}/{site}/{environment}/{locale}/bv.js`
- `https://display.ugc.bazaarvoice.com/static/{client}/{site}/{locale}/bvapi.js`

Search terms:

```bash
rg -io "(passkey|displaycode|api\\.bazaarvoice|reviews\\.json|products\\.json|batch\\.json|hasphotos).{0,200}"
```

Useful review filters:

- `filter=productid:eq:{product_id}`
- `filter=isratingsonly:eq:false`
- `filter=hasphotos:eq:true`
- `filter=hasmedia:eq:true`
- `sort=submissiontime:desc`
- `limit=100`
- `offset={n}`

Useful fields from review payloads:

- `ReviewText`, `Title`, `UserNickname`, `SubmissionTime`, `Rating`
- `Photos[].Sizes.normal.Url` or `Photos[].Sizes.large.Url`
- `AdditionalFields.SizePurchased`, `AdditionalFields.UsualSize`
- `ContextDataValues.Height`, `Weight`, `BodyType`, `Age`
- `OriginalProductName`, `ProductId`, `ContentLocale`

Useful product fields:

- `Name`, `Brand`, `ImageUrl`, `ProductPageUrl`, `FamilyIds`, `Attributes`
- `ReviewStatistics.TotalReviewCount`
- `ReviewStatistics.TotalPhotoCount`
- `ReviewStatistics.ContextDataDistribution`

### Loox

Common clues:

- `loox_global_hash`
- `looxReviews`
- `loox.io/widget/{client_id}/reviews/{product_id}`

For Shopify merchants, the product id may be in the PDP HTML or
`products.json`. Enell used this path successfully.

### Okendo

Common clues:

- `okendo` scripts or store id.
- Public URLs shaped like:
  `/stores/{store_id}/products/shopify-{product_id}/reviews`
  or store-wide review feeds.

Check whether review media is embedded directly or whether product images need
to be joined to review rows. Label image source type honestly.

### Yotpo

Common clues:

- Public app key in PDP/category HTML.
- Aggregate/product review JSON endpoints.

Yotpo feeds often expose only a small number of media reviews even when total
review count is high. Page until no more media or until the provider reports
exhaustion.

### TurnTo / Emplifi / Pixlee / PowerReviews

Use browser observation first:

- Identify script host and public site key.
- Look for review/media JSON URLs in public scripts or network resources.
- If only an iframe exposes media, inspect iframe query params for public
  `widget_id`, `product_id`, and `api_key`.
- Do not scrape from account-specific or challenge-specific requests.

## Required Output Contract

For review-image intake CSVs, include the usual Step 1 fields:

- `original_url_display`
- `image_source_type`
- `image_source_detail`
- `product_page_url_display`
- `user_comment`
- `reviewer_name_raw`
- `date_review_submitted_raw` / `review_date`
- size and measurement fields when exposed
- product title/category/variant context

For `staging.product_pages`, emit a sidecar CSV/JSONL with:

- `normalized_product_page_url`
- `source_site`
- `brand`
- `product_title_raw`
- `product_category_raw`
- `category_breadcrumb_path`
- `title`
- `breadcrumb`
- `url_slug`
- `json_ld_product_core`
- `json_ld_product_description`
- `description`
- `catalog_image_url`
- `catalog_image_urls`
- `catalog_image_source`
- `observed_clothing_type_ids`
- `source_status`
- `robots_disallowed`
- `first_seen_at`
- `last_seen_at`
- `raw_metadata`

If the shared `extractTaxonomy()` classifier is not run during scrape, set
`category_extractor_version=not_run_at_scrape_time`, keep
`needs_manual_review=true`, and preserve the raw signals so the classifier can
run later without a re-fetch.

## Lulus Retry Checklist

Older Lulus live attempts were blocked by PerimeterX from command-line and
fresh Playwright. Before retrying the old live endpoint directly:

1. Open a known Lulus review-photo PDP in visible browser.
2. Trigger reviews and image review UI.
3. Inspect scripts/resource URLs for provider clues instead of only retrying the
   blocked Nuxt endpoint.
4. Search public JS/config for review API keys and media filters.
5. If Lulus still exposes server-rendered Nuxt review payloads in the browser,
   identify whether the payload is present in static page state or comes from a
   public API request.
6. If a public API exists, build a clean provider scraper plus product-page
   sidecar.
7. If the only path requires PerimeterX/session replay, keep using workbook
   conversion or manual export and mark fresh live scrape blocked.

## Completion Checklist

- [ ] Public source and provider documented.
- [ ] No cookies/session/challenge tokens used.
- [ ] Review CSV written and validated.
- [ ] Product-page sidecar written and validated.
- [ ] Summary JSON includes rows, distinct images, distinct reviews, product
  page counts, measurement counts, strict qualified counts, and error counts.
- [ ] Retailer-specific doc updated with current outcome.
- [ ] `AGENT_LOG.md` updated for cross-agent handoff.
