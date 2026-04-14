# Product-Reviewer Image Concentration Report

Source: finished approval-batch chunk files in `data/step_3_image_annotation/machine_annotated_outputs/images_to_approve_part_*.csv`.

## Summary

- Total image rows analyzed: 91,925
- Unique product-reviewer combinations: 30,279
- Average images per product-reviewer combination: 3.04
- Median images per product-reviewer combination: 2
- 90th percentile images per combination: 4
- 95th percentile images per combination: 8
- Max images for a single product-reviewer combination: 102
- Rows missing product ID/ASIN: 0
- Rows missing reviewer ID: 42,198

## Concentration Thresholds

| Threshold | Combos at/above threshold | Share of combos | Image rows in those combos | Share of rows |
|---|---:|---:|---:|---:|
| 2+ images | 18,416 | 60.8% | 80,062 | 87.1% |
| 3+ images | 10,042 | 33.2% | 63,314 | 68.9% |
| 4+ images | 3,583 | 11.8% | 43,937 | 47.8% |
| 5+ images | 2,676 | 8.8% | 40,309 | 43.8% |
| 6+ images | 2,196 | 7.3% | 37,909 | 41.2% |
| 8+ images | 1,521 | 5.0% | 33,616 | 36.6% |
| 10+ images | 1,208 | 4.0% | 30,986 | 33.7% |
| 15+ images | 771 | 2.5% | 25,887 | 28.2% |
| 20+ images | 589 | 1.9% | 22,839 | 24.8% |

## Exact Distribution

| Images per combo | Number of combos | Share of combos |
|---|---:|---:|
| 1 | 11,863 | 39.2% |
| 2 | 8,374 | 27.7% |
| 3 | 6,459 | 21.3% |
| 4 | 907 | 3.0% |
| 5 | 480 | 1.6% |
| 6 | 432 | 1.4% |
| 7 | 243 | 0.8% |
| 8 | 187 | 0.6% |
| 9 | 126 | 0.4% |
| 10+ | 1,208 | 4.0% |

## Top 25 Most Repeated Product-Reviewer Combinations

| Rank | Images | ASIN | Reviewer ID | Product URL | Reviewer URL |
|---|---:|---|---|---|---|
| 1 | 102 | B076VPFHX2 | (missing) | https://www.amazon.com/dp/B076VPFHX2/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 2 | 98 | B07H1TLR76 | (missing) | https://www.amazon.com/dp/B07H1TLR76/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 3 | 98 | B08NY78VL6 | (missing) | https://www.amazon.com/dp/B08NY78VL6/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 4 | 95 | B07GYTLG1P | (missing) | https://www.amazon.com/dp/B07GYTLG1P/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 5 | 93 | B083GFGTRK | (missing) | https://www.amazon.com/dp/B083GFGTRK/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 6 | 91 | B07R1SJ7RC | (missing) | https://www.amazon.com/dp/B07R1SJ7RC/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 7 | 86 | B079FHBMKQ | (missing) | https://www.amazon.com/dp/B079FHBMKQ/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 8 | 85 | B07XM5T7B5 | (missing) | https://www.amazon.com/dp/B07XM5T7B5/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 9 | 84 | B09ZQFBZGJ | (missing) | https://www.amazon.com/dp/B09ZQFBZGJ/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 10 | 83 | B0734RTVYZ | (missing) | https://www.amazon.com/dp/B0734RTVYZ/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 11 | 83 | B0B9RHLNDQ | (missing) | https://www.amazon.com/dp/B0B9RHLNDQ/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 12 | 83 | B06XT44DDM | (missing) | https://www.amazon.com/dp/B06XT44DDM/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 13 | 83 | B07MZRHM63 | (missing) | https://www.amazon.com/dp/B07MZRHM63/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 14 | 82 | B017XIM7T8 | (missing) | https://www.amazon.com/dp/B017XIM7T8/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 15 | 82 | B097889NST | (missing) | https://www.amazon.com/dp/B097889NST/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 16 | 81 | B01N7GBXFV | (missing) | https://www.amazon.com/dp/B01N7GBXFV/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 17 | 81 | B07QKWZMHS | (missing) | https://www.amazon.com/dp/B07QKWZMHS/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 18 | 80 | B0BWXLR8YM | (missing) | https://www.amazon.com/dp/B0BWXLR8YM/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 19 | 80 | B07CP4544W | (missing) | https://www.amazon.com/dp/B07CP4544W/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 20 | 80 | B0788N3N8K | (missing) | https://www.amazon.com/dp/B0788N3N8K/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 21 | 79 | B093PNJTW3 | (missing) | https://www.amazon.com/dp/B093PNJTW3/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 22 | 78 | B00D77YC20 | (missing) | https://www.amazon.com/dp/B00D77YC20/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 23 | 78 | B09VBYQBDS | (missing) | https://www.amazon.com/dp/B09VBYQBDS/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 24 | 77 | B07DGRYRR1 | (missing) | https://www.amazon.com/dp/B07DGRYRR1/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |
| 25 | 77 | B00NOU4TCI | (missing) | https://www.amazon.com/dp/B00NOU4TCI/ref=cm_cr_arp_d_product_top?ie=UTF8 |  |

## Interpretation

- This issue is real if many rows are concentrated in a relatively small number of product-reviewer pairs.
- A hard cap such as 3, 4, or 5 images per product-reviewer pair would materially reduce repeated-image concentration while preserving broad coverage.
- The threshold table above is the most useful place to choose that cap.

## Top Products By Image Volume

| Rank | Images | Product ID |
|---|---:|---|
| 1 | 193 | B00NOU4TCI |
| 2 | 176 | B081GKNJV4 |
| 3 | 166 | B07PN7W2QP |
| 4 | 156 | B07GDZGDYN |
| 5 | 155 | B07318143V |
| 6 | 152 | B07CNC157C |
| 7 | 151 | B0CYGJDHRC |
| 8 | 145 | B0B1Z22VYN |
| 9 | 144 | B07D137NMH |
| 10 | 142 | B07KYXVKMC |
| 11 | 139 | B07RHXY66D |
| 12 | 139 | B00S9R0MPO |
| 13 | 134 | B0C1KTBF16 |
| 14 | 124 | B07R75YS8L |
| 15 | 123 | B08DHHVQVG |

## Top Reviewers By Image Volume

| Rank | Images | Reviewer ID |
|---|---:|---|
| 1 | 42,198 | (missing) |
| 2 | 175 | amzn1.account.AG7G7EMVTYDRYCSQC6TAQJVD6CNQ |
| 3 | 119 | amzn1.account.AH5GPDKKJSNKESXO5H2DXF2CTMIQ |
| 4 | 84 | amzn1.account.AGBHBDVHEVFEDWYBFQBC23WTKMVA |
| 5 | 73 | amzn1.account.AFUMMFQQQRAV26F4GYANUIE5JYAA |
| 6 | 69 | amzn1.account.AFM2WR3UCMDACHYHBLJLWDPF3YNA |
| 7 | 67 | amzn1.account.AGHNVG346CXZKLIC7AOAEY26LUQA |
| 8 | 56 | amzn1.account.AHGIDR4IJFS23Q4GTZ33FI5LYDSQ |
| 9 | 56 | amzn1.account.AFZJHV6DNDF5IJEG4PBUBJ65L4IA |
| 10 | 50 | amzn1.account.AGNOSAIUDOTQRVM2W26K3NVZPWMA |
| 11 | 49 | amzn1.account.AGX7VSIG4GOLW2L3OC2IP5E7AC7Q |
| 12 | 47 | amzn1.account.AEJKWCYG2MAPYZEZM7LOZE7ESWYA |
| 13 | 44 | amzn1.account.AFTP676UYEDVCDRACYZMRK7HO5MQ |
| 14 | 42 | amzn1.account.AFKRNVWRJS3E7ME4TIOLRWNZDQ4A |
| 15 | 41 | amzn1.account.AGU44MEMPU7PEPOHRLYHK5G4LASQ |
