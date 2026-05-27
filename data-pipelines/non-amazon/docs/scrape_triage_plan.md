# Non-Amazon Scrape Triage Plan

Last updated: 2026-05-27 America/New_York

## Coordination Rules

- Before starting a scrape, check both claim directories:
  - `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_active_scrape_claims`
  - `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_claims`
- Add a claim file before starting a new site so concurrent Codex chats do not duplicate work.
- Do not start a site already listed as active or claimed unless the claim is stale and the user confirms it is safe to take over.
- Default to first-time scrapes. Completed claim files in `_claims` are historical notes, not active queue items. Do not choose a completed retailer for another run unless the user explicitly asks for a refresh/resume, the prior result is marked blocked/partial/incomplete, or the triage plan clearly says it needs revisit.
- When picking "the next" scrape, skip completed retailers and choose an unclaimed site with no completed output/claim from the sheet intake or `Next Candidates` lists before considering any old refresh.
- The completed Sovrn Commerce triage is now part of this scrape triage. Use `data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv` for the sortable Sovrn candidate list, and check the full tracker before promoting a Sovrn merchant into implementation.
- Before assigning "next," search the repo and data root for the merchant domain/slug across scripts, docs, `_claims`, `_active_scrape_claims`, and output directories. Any hit means the site is already attempted and is not eligible as a first-time scrape unless the user explicitly names it or asks for a revisit/resume.
- If a site returns `429`, captcha, auth wall, WAF challenge, or suspicious-request behavior, stop retrying and mark it for revisit instead of increasing request pressure.
- Do not reject a site just because it lacks customer-photo reviews. Some useful sites expose catalog model images plus model height/size/measurements. For those, scrape the model image and model measurements, and mark rows with `image_source_type=catalog_model_image` instead of treating the image as a customer review image.
- For customer review photos, use `image_source_type=customer_review_image`. Existing shared helper rows default to this value.

## Active / Claimed

User confirmed on 2026-05-17 that there are no active scrapes happening right now. Old active claim files were cleared from both `_active_scrape_claims` directories; completed, blocked, and historical notes remain in `_claims` where present.

Completed/revisit claim notes, not the default first-time queue:

1. `stackathletics_com`: completed first-time full public Shopify/Okendo run on 2026-05-11. Output has 27 customer-image rows, 8 rows with measurements, 6 rows with ordered size, and 3 Supabase-qualified rows from 54 scanned products / 83 review pages.
2. `svahausa_com`: completed first-time public Shopify catalog-model run on 2026-05-11. Output has 465 catalog-model rows, 465 rows with measurements, 465 rows with ordered size, 0 strict customer-review Supabase-qualified rows, and 465 catalog-model qualified rows from 1,018 scanned products / 0 review pages. Coverage is exhaustive for the public Shopify catalog; no usable public customer-review media feed was found.
3. `ever_pretty_com`: completed first-time public sitemap/Judge.me media run on 2026-05-11. Output has 1,444 customer-image rows, 833 rows with measurements, 442 rows with ordered size, and 430 Supabase-qualified rows from 749 discovered products / 63 non-empty review pages. Coverage is exhaustive for the public sitemap plus public Judge.me media feed.
4. `ladyblacktie_com`: completed first-time public sitemap/Judge.me media run on 2026-05-11. Output has 250 customer-image rows, 64 rows with measurements, 0 rows with ordered size, and 0 Supabase-qualified rows from 2,884 discovered products / 9 non-empty review pages. Coverage is exhaustive for the public sitemap plus public Judge.me media feed; size remains `unknown` because public review HTML did not expose clean structured size answers.
5. `petalandpup_com`: completed full-catalog refresh/resume through current empty page 29 on 2026-05-11. Output remains 16,945 rows and 11,604 qualified rows after delta dedupe; no fresh 429/captcha/WAF.
6. `andieswim_com`: retry after strong smoke. Prior 60-product sample wrote 110 rows and 106 qualified rows; prefer store-feed-only mode or slow checkpointed catalog.
7. `swimoutlet_com`: checkpointed partial resume reached 2,090 Okendo store-review pages / 209,000 reviews and wrote 611 final deduped rows; feed still has `nextUrl`, continue later only in store-feed-only chunks if needed.
8. `miraclesuit_com`: completed 2026-05-06 sitewide rerun with fixed Yotpo size parser and 1.5s delay. Output matched corrected prior counts: 44 rows and 8 qualified rows.
9. `liverpoolstyle_com`: completed refreshed full public Shopify/Klaviyo run on 2026-05-11; output still has 12 customer-image rows and 2 qualified rows, with updated catalog coverage of 665 products.
10. `barse_com`: repeat public Shopify/Judge.me confirmation completed on 2026-05-14 after older non-`.claim` notes had already marked it out of scope. Output has 0 rows. The public catalog had 1,676 products, almost entirely jewelry, and public Judge.me media probes exposed no customer review image rows.
11. `curvykate_com`: completed full public catalog product-page scrape on 2026-05-14. Scanned all 278 public Shopify products/product pages, 173 Feefo parent SKUs, and 174 Feefo review pages. Output has 33,446 Feefo text-review rows joined to all public Shopify product-gallery images, 0 customer review image rows. Feefo media-gallery endpoint checked across all parent SKUs and returned no public customer media.
12. `unboundmerino_com`: completed full public catalog product-page scrape on 2026-05-14. Scanned all 152 public Shopify products/product pages and 509 Okendo review pages. Output has 1,412 Okendo review rows joined to catalog product/variant images, 1,296 rows with ordered size, 145 rows with parsed measurements, and 0 customer review image rows.
13. `byltbasics_com`: completed full public sitemap product-page scrape on 2026-05-14. Scanned all 666 public product pages and 1,416 Okendo review pages. Output has 48,736 Okendo review rows joined to catalog product/variant images, 9,045 rows with ordered size, 10,248 rows with parsed measurements, and 0 customer review image rows.

Claim files live in:

- `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_active_scrape_claims`

## Needs Revisit

### saintandsofia_com

- Status: first-time model-measurement smoke scrape stopped on 2026-05-11 after `HTTP 429` at product 10 of 987.
- Current output: 0 rows. The public Shopify catalog exposed 987 products, and product pages contain model height/size text, but the run stopped before any rows were retained.
- Revisit plan:
  - Wait for a later cool-down window before retrying.
  - Resume slowly from product-page scanning, using the patched parser for product-page `Care & Fit` model text.
  - Keep public pages/endpoints only; no auth bypass, captcha bypass, WAF bypass, or aggressive retries.

### ripleyrader_com

- Status: first-time model-measurement scrape stopped on 2026-05-11 after `HTTP 429` at product 117 of 248.
- Current output: 50 catalog-model rows, 0 customer-image rows, 50 rows with ordered size and model height. Strict customer-review Supabase-qualified rows: 0; catalog-model qualified rows: 50.
- Product coverage: 248 products discovered from public Shopify `products.json`, product sitemap, and the sheet lead URL; 116 product pages scanned before the 429.
- Revisit plan:
  - Wait for a later cool-down window before retrying.
  - Resume from the unscanned tail rather than immediately re-probing the blocked URL.
  - Keep public pages/endpoints only; no auth bypass, captcha bypass, WAF bypass, or aggressive retries.

### andieswim_com

- Status: claimed and attempted on 2026-05-05 after prior header-only output.
- Useful finding: public Okendo endpoints expose review media plus ordered size and reviewer attributes; a 60-product smoke wrote 110 rows and 106 qualified rows.
- Problem encountered: the lower-traffic store-level adapter was added, but Shopify catalog discovery hit `HTTP 429 Too Many Requests` on `products.json` page 2.
- Action taken: stopped immediately to avoid retry pressure.
- Revisit plan:
  - Wait for a later scrape window before retrying.
  - Prefer a store-feed-only mode using Okendo review `productUrl`, `productName`, `productHandle`, and `productVariantName`, avoiding full catalog pagination.
  - If catalog context is required, retry with at least `--request-delay-seconds 2.0` and add catalog checkpoint/resume.
  - Keep public pages/endpoints only; no auth bypass, captcha bypass, WAF bypass, or aggressive retries.

### swimoutlet_com

- Status: checkpointed partial resume as of 2026-05-07.
- Current output: 611 final deduped rows, including 597 `customer_review_image` rows and 14 `catalog_model_image` rows; 62 qualified rows. The store-review checkpoint contains 2,714 raw retained customer rows before final dedupe.
- Product discovery: checkpointed public `products.json` discovery reached 25,000 products and public endpoint boundary at page 101; sitemap checkpoint has 44,902 product URLs.
- Store-review coverage: public Okendo store feed reached 2,090 pages / 209,000 reviews / 1,978 media reviews; the feed still has `nextUrl`, so this is not complete historical store-feed coverage.
- Implementation state: `scrape_swimoutlet_reviews.py` supports `--store-feed-only` to resume the Okendo checkpoint without reloading the very large product checkpoint.
- Revisit plan:
  - Continue only with `--store-feed-only --request-delay-seconds 3.0` and bounded `--limit-review-pages` chunks if deeper historical tail is needed.
  - Do not restart catalog discovery unless there is a specific reason; the product checkpoint is very large and the sitemap already gives broader product URL signal.
  - Keep public pages/endpoints only; no auth bypass, captcha bypass, WAF bypass, or aggressive retries.

### miraclesuit_com

- Status: completed sitewide rerun on 2026-05-06 with fixed Yotpo size parser and `--request-delay-seconds 1.5`.
- Output: 44 rows, 8 rows with size, 8 rows with measurements, 8 Supabase-qualified rows, 6 distinct qualified reviews.
- Product coverage: 1,067 products discovered and scanned; 1,412 review pages scanned; 116 products had review-image rows; no scrape errors.
- Comparison: rerun matched the corrected 2026-05-05 output on key counts.
- Image source mix: 44 `customer_review_image` rows and 0 `catalog_model_image` rows.
- Implementation note: `scrape_miraclesuit_reviews.py` now extracts size from Yotpo `custom_fields` when present and explicit text phrases such as `Size 10`, writes `image_source_type`, and stops immediately on 429/captcha/WAF-like responses.

### jennikayne_com

- Status: first-time full public Shopify/Yotpo scrape stopped on 2026-05-14 after `HTTP 503` at product 545 of 1,100.
- Current output: partial only, not a completed full-catalog scrape. It has 185 customer-image rows from 544 scanned product pages and 949 Yotpo review pages.
- Revisit plan:
  - Wait for a later cool-down window before retrying.
  - Resume from the unscanned tail rather than restarting the full catalog.
  - Keep public pages/endpoints only; no auth bypass, captcha bypass, WAF bypass, or aggressive retries.

## Next Candidates

After the five queued claim files above:

- `catchallstore_com`: completed partial public product-page crawl on 2026-05-06; catalog endpoints were challenged, output has 14 catalog-model rows.
- `89thandmadison_com`: completed full public Shopify catalog scrape on 2026-05-06; output has 789 catalog-model rows from 949 scanned products.
- `victoriassecret_com`: completed 2026-05-06 over the local 140-product `VSprodLinks` catalog. Output has 1,177 rows: 1,029 customer review image rows and 148 catalog model image rows.
- `urbanoutfitters_com`: partial product-page scrape completed 2026-05-06 over the local `UO_BigImages.xlsx` `prodLinks` catalog. The public review API probe returned a DataDome interstitial, and product-page scraping stopped at the first HTTP 403 per guardrail. Output has 158 catalog-model rows from SSR product state before the stop.
- `freepeople_com`: blocked on 2026-05-20. A single safe homepage probe returned HTTP 403 with DataDome/captcha-delivery challenge behavior, so no Bazaarvoice endpoint scrape was attempted. Output is a zero-row blocked summary.
- `oddbirdco_com`: lower priority follow-up. It already has a recent full-catalog-attempted run with 68 rows and 14 qualified rows, so inspect before rerunning.

## Sovrn Commerce Triage Added 2026-05-27

Source files:

- Full tracker: `data-pipelines/non-amazon/docs/sovrn_commerce_apparel_triage_tracker.csv`
- Sortable scrape-candidate list: `data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv`
- Full triage report: `data-pipelines/non-amazon/docs/sovrn_commerce_full_triage_report.md`

Completion summary:

- 1,012 of 1,012 Sovrn merchants checked.
- 43 rows reached `triage_candidate`.
- 19 are first-pass scrape candidates after obvious false-positive cleanup.
- 15 manual-review rows were reviewed by the user from the Google Sheet export.
- 1 manual-review row was approved as a category-specific scrape candidate.
- 2 manual-review rows were approved as existing-scraper refreshes.
- 12 manual-review rows were rejected as do-not-queue.
- 9 are false positives and should not be scraped.
- 7 broad marketplaces remain category-level manual-review items, not normal first-pass scrape targets.
- Shoes and footwear remain out of scope.

User-approved Sovrn items from manual review:

- `nordstromrack_com`: customer photos are present. Scrape the women's section only; do not run a whole-site scrape. User-provided sample PDP: `https://www.nordstromrack.com/s/calvin-klein-scuba-crepe-fit-flare-dress/7881634?origin=category-personalizedsort&breadcrumb=Home%2FWomen%2FClothing%2FDresses&color=419`.
- `whitehouseblackmarket_com`: picture reviews are present. Refresh the existing scraper/report rather than creating a new scraper.
- `quince_com`: picture reviews are present. Refresh the existing scraper rather than creating a new scraper.

Use this payout-prioritized Sovrn scrape order after checking claim/output history for each domain. Ranking uses estimated commission per click where Sovrn provided conversion rate, commission rate, and AOV; rows without enough data are ordered after the known-payout rows by CPA/CPC availability and triage quality.

1. `prettylittlething_com`: CPA+CPC; est. commission/click `$0.39`; conversion `11.81%`; commission `4.36%`; AOV `$75.73`; Bazaarvoice; `photo_reviews=yes`; shipping `AU|CA|FR|GB|IE|US`.
2. `nordstromrack_com`: CPA+CPC; est. commission/click `$0.25`; conversion `5.57%`; commission `3.45%`; AOV `$128.12`; customer photos present; scrape women's section only.
3. `spanx_com`: CPA+CPC; est. commission/click `$0.14`; conversion `2.97%`; commission `3.05%`; AOV `$155.25`; Yotpo; `photo_reviews=yes`; shipping `CA|GB|US`.
4. `clothingshoponline_com`: CPA+CPC; est. commission/click `$0.14`; conversion `4.17%`; commission `5.71%`; AOV `$59.55`; Yotpo/Loox signal; `photo_reviews=unknown_sample_too_small`; shipping `US`.
5. `whitehouseblackmarket_com`: refresh existing scraper; CPA+CPC; est. commission/click `$0.07`; conversion `7.0%`; commission `1.05%`; AOV `$89.02`; Bazaarvoice; picture reviews present.
6. `quince_com`: refresh existing scraper; CPA+CPC; est. commission/click `$0.07`; conversion `1.61%`; commission `3.0%`; AOV `$154.36`; Yotpo; picture reviews present.
7. `prettylittlething_com_au`: CPA; est. commission/click `$0.04`; conversion `1.6%`; commission `6.0%`; AOV `$43.61`; Bazaarvoice; `photo_reviews=yes`; shipping `AU|CA|FR|GB|IE|US`.
8. `yogademocracy_com`: CPA+CPC, payout fields not populated; Yotpo; `photo_reviews=yes`; shipping `US`.
9. `spinnakerboutique_com`: CPA+CPC; conversion `3.17%`, commission/AOV not populated; Loox; `photo_reviews=yes`; shipping `US`.
10. `luxefashionclothing_com`: CPA, payout fields not populated; provider unknown; `photo_reviews=yes`; shipping `US`.
11. `nojeans_co`: CPA+CPC, payout fields not populated; provider unknown; `photo_reviews=unknown_sample_too_small`; shipping `AU|CA|DE|ES|FR|GB|IT|NZ|US`.
12. `seven7jeans_com`: CPA+CPC, payout fields not populated; provider unknown; `photo_reviews=unknown_sample_too_small`; shipping `CA|US`.
13. `redrat_co_nz`: CPA+CPC, payout fields not populated; provider unknown; `photo_reviews=unknown_sample_too_small`; shipping unknown.
14. `wildsecretslingerie_com_au`: CPA+CPC, payout fields not populated; provider unknown; `photo_reviews=unknown_sample_too_small`; shipping `AU|NZ|US`.
15. `wildsecretslingerie_co_nz`: CPA, payout fields not populated; provider unknown; `photo_reviews=unknown_sample_too_small`; shipping `AU|NZ|US`.
16. `abrandjeans_com`: CPC, CPC amount not populated; Okendo; `photo_reviews=yes`; shipping `US`.
17. `lascana_com`: CPC, CPC amount not populated; Yotpo; `photo_reviews=yes`; shipping `DE|US`.
18. `foxylingerie_com`: CPC, CPC amount not populated; provider unknown; `photo_reviews=yes`; shipping `US`.
19. `rollasjeans_com`: CPC, CPC amount not populated; provider unknown; `photo_reviews=yes`; shipping `US`.
20. `synergyclothing_com`: CPC, CPC amount not populated; provider unknown; `photo_reviews=yes`; shipping `US`.
21. `tbdress_com`: CPC, CPC amount not populated; provider unknown; `photo_reviews=yes`; shipping `US`.
22. `lingerie_co_uk`: CPC, CPC amount not populated; provider unknown; `photo_reviews=unknown_sample_too_small`; shipping `GB`.

Sovrn manual-review rows rejected by user:

- `boohoo_com`, `boohoo_com_no`: no reviews available.
- `boohooman_com`: out of scope; no women's clothing.
- `mugsyjeans_com`: out of scope; no women's clothing.
- `getlambs_com` / `havnwear_com`: only one non-hat product; skip.
- `chicos_com`, `chicosofftherack_com`: no picture reviews.
- `clothesoutdoor_com`: website is broken.
- `senseng_apparel_com`: not enough products to be worth scraping.
- `puma_com`: no reviews.
- `shopbop_com`: no reviews.
- `nau_com`: all items listed as not for sale.

Sovrn false positives to avoid:

- `iloveantix_com`: accessory/board-product false positive.
- `evolveclothing_com`: men's category/cookie URL false positive.
- `jeans_meile_de`: men's category false positive.
- `petiterevery_com`: kids category false positive.
- `rococlothing_co_uk`: kids category false positive.
- `boutique_dmc_fr` / `dmc_com`: yarn/craft-products false positive.
- `ventilateurs_plafond_com`: ceiling-fan false positive.
- `gillettevenus_com`: razor/personal-care false positive.
- `nuawoman_com`: wellness/content false positive.

## Sheet Intake Added 2026-05-06

Source workbook: `Scrape These Too` (`verifiedLinks`, `unverfiedLinks`, `NotScrapable` tabs).

New or newly emphasized verified links to incorporate into future triage/probing:

- `89thandmadison_com`: completed 2026-05-06. Full public Shopify catalog scrape emitted catalog model image rows, not customer-image rows.
- `altardstate_com`: dress/product-page targets.
- `aliava_com`: dress target.
- `boden_com`: note says model height and size only. Treat as catalog-model scrape, not customer-image scrape.
- `oxknit_com`: apparel target.
- `lacemade_com`: dress target.
- `branwyn_com`: two bra/bralette targets.
- `shoplarken_com`: bra target with Judge.me anchor.
- `boody_com`: wireless bra target.
- `wearpepper_com`: bra target.
- `lulalu_com`: bra target.
- `thelittlebracompany_com`: strapless bra target.
- `getfitcherries_com`: petite push-up bra target.
- `thirdlove_com`: bra target.
- `woolx_com`: women's pants target.
- `scottevest_com`: women's travel jacket target.
- `wearfigs_com`: women's jacket target.
- `popflexactive_com`: leggings/sklegging target.

Good/unverified sheet entries not yet fully incorporated into adapter triage:

- `swimsuitsforall_com`
- `catherines_com`
- `citychiconline_com`
- `hollisterco_com`
- `torrid_com`
- `landsend_com`
- `oldnavy_com`
- `seafancy_com`
- `summersalt_com`
- `rosewe_com`
- `azazie_com`
- `jcrew_com`
- `bodenusa_com`
- `ariat_com`
- `unboundmerino_com`
- `lagence_com`
- `duluthtrading_com`
- `kuhl_com`
- `kimesranch_com`
- `eddiebauer_com`
- `byltbasics_com`

Sheet entries marked no / not useful / not scrapable:

- From `unverfiedLinks`: `kohls_com`, `nastygal_com`, `boohoo_com`, `fashionnova_com`, `bloomingjelly_com`, `speedo_com`, `lanebryant_com`, `asos_com`, `buckle_com` (can't find reviews).
- From `NotScrapable`: `negativeunderwear_com`, `mariejo_com`, `meundies_com`, `vuoriclothing_com`, `longtallsally_com`, `jjill_com`, `chicos_com`, `americantall_com`, `angeljackets_com`, `lilysilk_com`.

## Sheet Intake Added 2026-05-11

Source workbook rechecked: `Scrape These Too` (`verifiedLinks`, `unverfiedLinks`, `NotScrapable` tabs), spreadsheet ID `1Kw7JWjvX1HyrEEirLBr-9ghbvi3RAE4p2mEWuzDpCv8`.

New verified/product-link entries not yet represented in this triage plan:

- `ripleyrader_com`: wide-leg cropped pant; sheet note says model measurements only. Treat as catalog-model scrape.
- `saintandsofia_com`: Bowie stretch flare jean; sheet note says model measurements only. Treat as catalog-model scrape.
- `stackathletics_com`: Courtside dress target.
- `ever_pretty_com`: formal/evening dress target.
- `svahausa_com`: twirl dress target.
- `afends_com`: women's seersucker maxi dress target.
- `betabrand_com`: dress pant yoga pant; sheet note says model measurements only. Treat as catalog-model scrape.
- `titlenine_com`: women's corduroy shorts target.
- `ladyblacktie_com`: formal gown target.
- `cozyearth_com`: women's pajama set target with `#reviews`.
- `karinadresses_com`: dress target.
- `livesozy_com`: additional dress target.
- `curveins_com`: plus-size evening dress target.
- `wedtrend_com`: wedding-party dress target.
- `jessakae_com`: dress targets.
- `berylove_com`: formal dress target.
- `showmeyourmumu_com`: maxi dress target.
- `macduggal_com`: formalwear target.
- `missacc_com`: bridesmaid dress target.
- `stacees_com`: bridesmaid dress target with reviews anchor typo in URL.
- `rujutasheth_com`: jumper target with Loox reviews frame anchor.
- `shop_dia_com`: plus-size cape gown target.
- `shoprevelry_com`: applique dress target.
- `mondressy_com`: mother-of-the-bride dress target.
- `mollyevers_com`: bridesmaid dress target.
- `linticoshop_com`: linen midi dress target.
- `daisysilk_com`: silk dress target.
- `gracins_com`: formal dress target.
- `nafori_com`: formal/evening dress target.
- `awbridal_com`: bridesmaid dress target.
- `missord_com`: jumpsuit target.
- `jennikayne_com`: dress target.

New unverified links to check before assigning scraper work:

- `ruti_com`: crop straight jeans target.
- `sanctuaryclothing_com`: marine jean target.
- `nation_la`: tank target.

New entries marked not scrapable / no useful scrape in the sheet:

- `staud_clothing`
- `carolmargaret_wilmington_com`

## Avoid For Now

- `kennethcole_com`: public Yotpo feed exists, but sampled aggregate pages show zero customer image attachments; skip unless a different public media source appears.
- `686_com`: public Yotpo feed exists, but sampled aggregate pages and product `reviewsMedia` show zero customer image attachments; skip unless a different public media source appears.
- `alloyapparel_com`: prior summary already recorded `HTTP 429`; wait for cool-down before any rescue.
- `baiia_co`, `hue_com`, `tnuck_com`, `kiyonna_com`: prior zero-row summaries already recorded `HTTP 429`; avoid repeat probing for now.
- `missme_com`: active concurrent scrape.
- `premcurve_com`: claimed.
- `swimoutlet_com`: active claim now blocked by 429; wait for cool-down/resume plan.
- `andieswim_com`: active claim now blocked by 429; wait for cool-down or store-feed-only revisit.
- `breakoutbras_com`: recent run exists from 2026-05-05 with 147 rows and 73 qualified rows; summarize/report before considering any rerun.
- `barse_com`: completed 2026-05-14 with no public review-image rows and no apparel/model-fit signal; skip unless a new public media source appears.
- `us_princesspolly_com`: deferred on 2026-05-14 because the public Shopify catalog has 15,843 products and about 13,375 live apparel products. Do not treat the removed 3-product smoke as a scrape dataset; only revisit with an explicit large-crawl plan.
- `kimesranch_com`: blocked on 2026-05-14 when public `products.json` returned an HTTP 403 verification response during deeper probe; skip until a later cool-down or a different public source is identified.
