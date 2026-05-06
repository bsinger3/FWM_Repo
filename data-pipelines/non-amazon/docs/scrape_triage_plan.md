# Non-Amazon Scrape Triage Plan

Last updated: 2026-05-06 America/New_York

## Coordination Rules

- Before starting a scrape, check both claim directories:
  - `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_active_scrape_claims`
  - `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_claims`
- Add a claim file before starting a new site so concurrent Codex chats do not duplicate work.
- Do not start a site already listed as active or claimed unless the claim is stale and the user confirms it is safe to take over.
- If a site returns `429`, captcha, auth wall, WAF challenge, or suspicious-request behavior, stop retrying and mark it for revisit instead of increasing request pressure.
- Do not reject a site just because it lacks customer-photo reviews. Some useful sites expose catalog model images plus model height/size/measurements. For those, scrape the model image and model measurements, and mark rows with `image_source_type=catalog_model_image` instead of treating the image as a customer review image.
- For customer review photos, use `image_source_type=customer_review_image`. Existing shared helper rows default to this value.

## Active / Claimed

User confirmed on 2026-05-06 that there are no other active Codex threads. Old active claim files from completed/skipped May 5 work were cleared from `_active_scrape_claims`; completed notes remain in `_claims` where present.

Current queued claim files:

1. `petalandpup_com`: resume full catalog from partial output. Prior bounded run wrote 947 rows and 688 qualified rows; public Yotpo worked, but catalog continuation hit 429.
2. `andieswim_com`: retry after strong smoke. Prior 60-product sample wrote 110 rows and 106 qualified rows; prefer store-feed-only mode or slow checkpointed catalog.
3. `swimoutlet_com`: resume with slow catalog/checkpointing. Prior discovery reached products.json page 8 after 1,750 product records, then stopped on 429.
4. `miraclesuit_com`: completed 2026-05-06 sitewide rerun with fixed Yotpo size parser and 1.5s delay. Output matched corrected prior counts: 44 rows and 8 qualified rows.
5. `liverpoolstyle_com`: inspect/refresh the existing small output; triage sheet has 58 review-media hints and no active conflict.

Claim files live in:

- `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_active_scrape_claims`

## Needs Revisit

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

- Status: claimed and attempted on 2026-05-05 after the previous seed-only scrape.
- Problem encountered: full catalog discovery via public Shopify `products.json` hit `HTTP 429 Too Many Requests` on page 8 after pages 1-7 returned 1,750 product records.
- Action taken: stopped retrying immediately to avoid suspicious or high-pressure traffic.
- Implementation state: `scrape_swimoutlet_reviews.py` was added and a targeted Okendo sanity check against the known seed product returned image rows with ordered size/color from `productVariantName`.
- Revisit plan:
  - Wait for a later scrape window before retrying.
  - Rerun with a much slower catalog delay, at least `--request-delay-seconds 2.0`.
  - Consider adding catalog checkpoint/resume before retrying, so a future 429 does not discard already discovered product pages.
  - Keep the active claim file until this is either resumed or deliberately released.

### miraclesuit_com

- Status: completed sitewide rerun on 2026-05-06 with fixed Yotpo size parser and `--request-delay-seconds 1.5`.
- Output: 44 rows, 8 rows with size, 8 rows with measurements, 8 Supabase-qualified rows, 6 distinct qualified reviews.
- Product coverage: 1,067 products discovered and scanned; 1,412 review pages scanned; 116 products had review-image rows; no scrape errors.
- Comparison: rerun matched the corrected 2026-05-05 output on key counts.
- Image source mix: 44 `customer_review_image` rows and 0 `catalog_model_image` rows.
- Implementation note: `scrape_miraclesuit_reviews.py` now extracts size from Yotpo `custom_fields` when present and explicit text phrases such as `Size 10`, writes `image_source_type`, and stops immediately on 429/captcha/WAF-like responses.

## Next Candidates

After the five queued claim files above:

- `catchallstore_com`: completed partial public product-page crawl on 2026-05-06; catalog endpoints were challenged, output has 14 catalog-model rows.
- `89thandmadison_com`: completed full public Shopify catalog scrape on 2026-05-06; output has 789 catalog-model rows from 949 scanned products.
- `victoriassecret_com`: completed 2026-05-06 over the local 140-product `VSprodLinks` catalog. Output has 1,177 rows: 1,029 customer review image rows and 148 catalog model image rows.
- `urbanoutfitters_com`: partial product-page scrape completed 2026-05-06 over the local `UO_BigImages.xlsx` `prodLinks` catalog. The public review API probe returned a DataDome interstitial, and product-page scraping stopped at the first HTTP 403 per guardrail. Output has 158 catalog-model rows from SSR product state before the stop.
- `freepeople_com`: Bazaarvoice target from two sheet URLs; medium difficulty, likely adapter/API inspection.
- `oddbirdco_com`: lower priority follow-up. It already has a recent full-catalog-attempted run with 68 rows and 14 qualified rows, so inspect before rerunning.

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
