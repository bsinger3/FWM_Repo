# Reviewer Cap Impact Report

Source: usable rows from finished chunk files in `data/step_3_image_annotation/machine_annotated_outputs/images_to_approve_part_*.csv`, where usable means `has_person_REVIEWONLY = true`.

## Reviewer Identity Rule

- Use reviewer profile ID when `reviewer_profile_url` is present.
- Otherwise fall back in this order:
  1. `reviewer_name_raw + review_date + hash(user_comment)`
  2. `review_date + hash(user_comment)`
  3. `hash(user_comment)`
  4. `reviewer_name_raw + review_date`
  5. `reviewer_name_raw`

## Summary

- Total usable images (`has_person_REVIEWONLY = true`): 57,127
- Usable rows with profile-based reviewer ID: 28,983
- Usable rows using fallback reviewer identity: 28,144
- Unique product-reviewer combinations under smart fallback: 40,044
- Median usable images per smart reviewer-product combination: 1
- Max usable images for one smart reviewer-product combination: 12

## Fallback Coverage

| Fallback type | Rows | Share of usable rows |
|---|---:|---:|
| profile | 28,983 | 50.7% |
| name_date_comment | 15 | 0.0% |
| date_comment | 346 | 0.6% |
| comment | 27,783 | 48.6% |
| name_date | 0 | 0.0% |
| name | 0 | 0.0% |
| missing | 0 | 0.0% |

## Cap Impact

| Cap per reviewer-product pair | Kept usable images | Removed usable images | Share removed | Combos affected |
|---|---:|---:|---:|---:|
| 2 | 53,555 | 3,572 | 6.3% | 2,973 |
| 3 | 56,528 | 599 | 1.0% | 329 |
| 4 | 56,857 | 270 | 0.5% | 133 |

## Comparison To Profile-Only Cap

- Earlier profile-only estimate for cap 2 kept `33,430` usable images.
- Smart fallback keeps `53,555` usable images at cap 2.
- That preserves `20,125` more usable images than the profile-only method.

## Top 25 Most Repeated Smart Reviewer-Product Combinations

| Rank | Images | Product ID | Reviewer key type | Reviewer key |
|---|---:|---|---|---|
| 1 | 12 | B0DHGZCCRJ | profile | amzn1.account.AGNOSAIUDOTQRVM2W26K3NVZPWMA |
| 2 | 10 | B0DT596W8K | profile | amzn1.account.AFUCFJLCNU2PXAQ5SMG56WH5X25Q |
| 3 | 10 | B092JNJH97 | profile | amzn1.account.AEJGW5CFJFIYTXGEZFECL45BL5BQ |
| 4 | 10 | B09YLFZ7ZP | profile | amzn1.account.AH745EWUKTVXNM5JW552YAHDBFKA |
| 5 | 10 | B0D66YDTMP | profile | amzn1.account.AGNM3WIT6QUUZYQI7C4RED7SDMEA |
| 6 | 9 | B07B6N6K8Y | profile | amzn1.account.AHEMHOZGCYPWVDNZMH6CLEADX7MQ |
| 7 | 9 | B07RY441CF | profile | amzn1.account.AHEMHOZGCYPWVDNZMH6CLEADX7MQ |
| 8 | 9 | B0FNQM9ZZD | profile | amzn1.account.AFUMMFQQQRAV26F4GYANUIE5JYAA |
| 9 | 8 | B0F322ZXC5 | profile | amzn1.account.AFMVF7XFU2IU74D6MMQTUPWMFNLQ |
| 10 | 8 | B07R9H5DNM | profile | amzn1.account.AE25JHNAK5Q6T6GV2X4NRY6ABYBQ |
| 11 | 8 | B0C5NDQ9J7 | profile | amzn1.account.AEBZLIWS75NW7KIJOAQZ5DCTNY2A |
| 12 | 8 | B092JMH6FN | profile | amzn1.account.AHAJ6Z6CSLUBMGLVMPGHPRIOOPPQ |
| 13 | 8 | B07R6343R2 | profile | amzn1.account.AHBQCAIFDGBBHGV5FELLGGIXIQ5A |
| 14 | 8 | B0G43RGRKH | profile | amzn1.account.AFWHW2U7C7Y7LC2MYD6IVRZ36RDQ |
| 15 | 8 | B0DR9WBNYC | profile | amzn1.account.AHWQ3EQ22PJ7XPJMHSXL5S7Y47CA |
| 16 | 8 | B0DR9WBNYC | profile | amzn1.account.AHR6WGUAW4B2XT2JDFO23NFBVDMA |
| 17 | 8 | B0C5CG7G5Y | profile | amzn1.account.AHDKHNKAHR6CEUI5ECS2VH7GTDTA |
| 18 | 7 | B09K1NW4WD | profile | amzn1.account.AFAL5XFULDFT45ZUI56MFPM5T3QA |
| 19 | 7 | B0BPP4B5XG | profile | amzn1.account.AFQS47JSXNLTFD5ODBGPKIJ3O6VQ |
| 20 | 7 | B0FW59CBPX | profile | amzn1.account.AED2UJG7O3K3LOEKCZGVEAMWS7BA |
| 21 | 7 | B0CC5FRD84 | profile | amzn1.account.AFQS47JSXNLTFD5ODBGPKIJ3O6VQ |
| 22 | 7 | B0FW5F9FCB | profile | amzn1.account.AED2UJG7O3K3LOEKCZGVEAMWS7BA |
| 23 | 7 | B0FLMMMNZ4 | profile | amzn1.account.AEAC4PHQMVGNKVP4JNLCNJRRMZ6A |
| 24 | 7 | B0FQCK5GLV | profile | amzn1.account.AFWHW2U7C7Y7LC2MYD6IVRZ36RDQ |
| 25 | 7 | B0G58GNR9Q | profile | amzn1.account.AHN5HPHMT7PT76MGR3IW5MJTGNKA |

## Recommendation

- If you want to reduce concentration without throwing away a huge number of usable rows, the smart fallback is much better than relying on profile URL alone.
- A cap of 2 is still pretty aggressive.
- A cap of 3 or 4 may be a better starting point if you want to preserve more reviewer/product coverage while still cutting down repeated images.
