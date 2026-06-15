# Net-New Gap Probe Round 2 - 2026-06-09

## Purpose

Follow-up probe after the successful Glamorise and Amalli Talli scrapes. This pass tested the next likely gap-fill candidates for accessible customer-photo review feeds with self-reported measurements.

## Promoted

No new site from this round was promoted to a scrape.

## Demoted Or Deferred

| Domain | Gap target | Probe result | Decision |
| --- | --- | --- | --- |
| `wacoal-america.com` | bra/full-bust | Public `products.json` works and PDPs contain measurement/review language, but sampled Okendo review endpoints returned empty review payloads. | Defer until a high-review product endpoint is found. |
| `brastop.com` | bra/full-bust | Public `products.json` works. PDPs use Feefo via `brastop-brand-parent`; Feefo product reviews are public, but sampled images were product/catalog images, not customer photos, and reviews did not expose height/weight/bra-size measurements. | Do not scrape for image-measurement gap coverage right now. |
| `understance.com` | bra/full-bust | Public pages render the same Remix shell across homepage/collections/search. No product URLs in sitemap or static HTML; no obvious review-provider keys. | Defer; needs browser/API reverse-engineering if revisited. |
| `bravissimo.com` | bra/full-bust | PDP app bundle exposes reviewer-size/write-review field labels, but no accessible customer-photo review feed was resolved in this pass. | Defer; good measurement semantics, unclear public review-media API. |
| `americantall.com` | tall women | Public `products.json` works and some women's PDPs are live, but many catalog handles are stale/404. PDPs include product/app metadata with height/weight terms but did not expose customer review content or a simple public review API. | Defer; Amalli Talli remains the better tall source. |
| `swimsuitsforall.com` | plus-size swim/body sizes | Pages expose body-language metadata and search/product-card content, but sampled PDPs/search surfaces did not expose customer-photo review provider config. | Defer. |
| `womanwithin.com` | plus-size apparel/body sizes | Similar FullBeauty/Demandware behavior; sampled product pages did not expose customer-photo review provider config. | Defer. |
| `avenue.com` | plus-size apparel/body sizes | Product cards are accessible, but sampled PDPs did not expose review provider or measurement-bearing customer-photo reviews. | Defer. |

## Current Priority After Round 2

1. `glamorise_com` remains the strongest net-new bra/full-bust source.
2. `amallitalli_com` remains the strongest net-new tall source.
3. `knix_com` and `skims_com` are useful second-tier Okendo sources.
4. The Round 2 candidates should not be queued for full scrape until a concrete public customer-photo review endpoint is resolved.
