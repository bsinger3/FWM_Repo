# Affiliate Aggregator Gap Sourcing Plan - 2026-06-09

## Recommendation

Register for one additional merchant-directory affiliate network before doing another broad internet sweep.

The goal is not affiliate revenue first. The goal is to get a structured list of apparel merchants that can be deduped against the existing Sovrn/lead triage and then probed for the exact data we need: customer review images plus self-reported height, weight, bra size, bust, waist, hips, inseam, pregnancy/postpartum context, petite/tall context, or plus/extended-size context.

## Best first network

### Awin

Why it should be first:

- It exposes an advertiser directory as a core publisher resource.
- It advertises broad brand coverage across fashion, retail, and related categories.
- It now appears more relevant than treating ShareASale as a separate path.
- It should give us enough merchant discovery surface to find smaller Shopify and DTC apparel brands that are more likely to use Loox, Okendo, Judge.me, Stamped, or Yotpo photo reviews.

What to export or capture:

- merchant name
- primary domain
- advertiser category
- country/market
- commission/payout type
- acceptance status
- deep-link support
- product feed availability
- any merchant description/category text

## Second-tier networks

### CJ

Use for larger retailers and established apparel programs. It is likely to overlap with brands we have already seen, but it may surface department-store and mall-brand sites with Bazaarvoice review photos.

### Rakuten Advertising

Use for higher-end, department-store, and fashion/retail brands. Expect more overlap and more large-retailer review systems, but still worth a pass after Awin.

### Impact

Use for modern DTC brands. It may be strong for Shopify-native apparel, shapewear, activewear, maternity, lingerie, and swim brands, but directory access may depend more on approval/account state.

### Partnerize

Use later if we need enterprise or international apparel coverage. It is probably less efficient as the next immediate move unless its directory is easy to export.

### ShopMy / LTK / creator-commerce platforms

These are useful for discovering culturally relevant apparel brands, but they are less ideal as the next operational source because we need a merchant table, not creator posts. Use them as a secondary research layer after merchant-directory networks.

## Merge workflow

1. Export or manually capture the network's apparel/fashion advertiser list.
2. Normalize each merchant to a domain key:
   - lowercase host
   - strip `www.`
   - strip country storefront prefixes when appropriate
   - preserve market domains when they expose different review systems
3. Dedupe against:
   - `FWM_Data/WebLeads/leads.csv`
   - `FWM_Repo/data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv`
   - `FWM_Repo/outputs/measurement_coverage/20260609_human_labeled_approved_only/lead_gap_reprioritization.csv`
   - existing folders under `FWM_Data/non-amazon/data/step_1_raw_scraping_data/`
   - existing claim files under `_claims/`
4. Keep only net-new or refresh-worthy merchants.
5. Score remaining merchants for gap fit before probing:
   - tall / long inseam
   - petite / short inseam
   - full bust / bra cup and band sizes
   - plus / extended size / high waist and hip measurements
   - maternity / postpartum
   - swim / shapewear
   - adaptive / mastectomy / specialty fit
6. Probe only top-scoring merchants for review-provider evidence:
   - Loox
   - Okendo
   - Judge.me
   - Stamped
   - Yotpo
   - Bazaarvoice
   - Feefo, only if customer media and measurement text are actually present
7. Promote only merchants with photo-review and measurement evidence into scrape candidates.

## Proposed output schema

Create a network-specific import file under:

`FWM_Repo/outputs/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/`

Recommended columns:

- `source_network`
- `merchant_name`
- `primary_domain`
- `normalized_domain`
- `network_category`
- `market`
- `commission_type`
- `commission_detail`
- `product_feed_available`
- `deep_link_available`
- `approval_status`
- `already_in_web_leads`
- `already_in_sovrn_triage`
- `existing_data_dir_found`
- `existing_scrape_doc_found`
- `existing_claim_found`
- `gap_tags`
- `gap_priority_score`
- `review_provider_probe`
- `photo_reviews_probe`
- `measurement_text_probe`
- `probe_notes`
- `recommended_action`

## Immediate next action

Apply to Awin as the next aggregator. Once access is available, export/capture the apparel/fashion advertiser directory and run it through a small dedupe and gap-scoring script before doing any more merchant-by-merchant internet research.

This should reduce wasted probing because every new candidate will already be:

- net-new relative to Sovrn and existing leads,
- category-relevant to the uncovered body-size gaps,
- likely to have a discoverable product/review surface.
