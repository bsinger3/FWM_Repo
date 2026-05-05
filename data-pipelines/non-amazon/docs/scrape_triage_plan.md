# Non-Amazon Scrape Triage Plan

Last updated: 2026-05-05 13:55 America/New_York

## Coordination Rules

- Before starting a scrape, check both claim directories:
  - `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_active_scrape_claims`
  - `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_claims`
- Add a claim file before starting a new site so concurrent Codex chats do not duplicate work.
- Do not start a site already listed as active or claimed unless the claim is stale and the user confirms it is safe to take over.
- If a site returns `429`, captcha, auth wall, WAF challenge, or suspicious-request behavior, stop retrying and mark it for revisit instead of increasing request pressure.

## Active / Claimed

- `missme_com`: active in another Codex chat as of 2026-05-05 13:45 America/New_York. Do not duplicate.
- `premcurve_com`: claimed by current/another Codex thread for full scrape on 2026-05-05. Do not duplicate.

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

- Status: completed full catalog scrape on 2026-05-05, then corrected output from already scraped rows.
- Output after correction: 44 rows, 8 rows with size, 8 rows with measurements, 8 Supabase-qualified rows, 6 distinct qualified reviews.
- Problem encountered: first adapter pass failed to extract ordered size from review text, so qualified rows were incorrectly reported as 0.
- Fix applied: `scrape_miraclesuit_reviews.py` now extracts size from Yotpo `custom_fields` when present and explicit text phrases such as `Size 10`.
- Network problem: immediate full rerun after the fix hit `HTTP 429 Too Many Requests` on `products.json`.
- Revisit plan:
  - Wait until a later scrape window before rerunning MiracleSuit.
  - Rerun with the fixed parser and conservative delay, starting at `--request-delay-seconds 1.5` or slower.
  - Keep public pages only; no auth bypass, captcha bypass, or aggressive retries.
  - Compare the rerun summary against the corrected output and confirm `rows_with_size`, `rows_with_any_measurement`, and `rows_supabase_qualified`.

## Next Candidates

- `oddbirdco_com`: lower priority follow-up. Summary says `still needs full scrape`, but it already has a recent full-catalog-attempted run with 59 rows and 14 qualified rows, so inspect before rerunning.
- `goelia1995_com`: candidate after SwimOutlet/Oddbird if the goal is filling zero-row merchants; current status is seed-only/no readable output.

## Avoid For Now

- `kennethcole_com`: public Yotpo feed exists, but sampled aggregate pages show zero customer image attachments; skip unless a different public media source appears.
- `686_com`: public Yotpo feed exists, but sampled aggregate pages and product `reviewsMedia` show zero customer image attachments; skip unless a different public media source appears.
- `alloyapparel_com`: prior summary already recorded `HTTP 429`; wait for cool-down before any rescue.
- `baiia_co`, `hue_com`, `tnuck_com`, `kiyonna_com`: prior zero-row summaries already recorded `HTTP 429`; avoid repeat probing for now.
- `missme_com`: active concurrent scrape.
- `premcurve_com`: claimed.
- `miraclesuit_com`: wait for cool-down before rerun because of 429.
- `swimoutlet_com`: active claim now blocked by 429; wait for cool-down/resume plan.
- `andieswim_com`: active claim now blocked by 429; wait for cool-down or store-feed-only revisit.
- `breakoutbras_com`: recent run exists from 2026-05-05 with 147 rows and 73 qualified rows; summarize/report before considering any rerun.
