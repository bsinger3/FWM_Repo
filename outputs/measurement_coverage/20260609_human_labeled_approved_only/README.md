# Measurement Coverage Snapshot

Generated: 2026-06-09 21:08:06 UTC

## Scope

- Unique rows scanned: 26,203
- Rows usable for body-size prospecting: 20,360
- Rows with both height and weight: 15,058
- Rows with any body-specific measurement beyond height/weight: 10,493

## Source Mix

- human_labeled: 26,203

Input rows before dedupe:

- human_labeled / human_labeled_returns: 26,286

## Coverage By Field

| field | rows_with_value | pct_of_unique_rows |
| --- | ---: | ---: |
| size_display | 26,203 | 100.0 |
| height_in_display | 23,813 | 90.88 |
| weight_lbs_display | 16,308 | 62.24 |
| inseam_inches_display | 6,989 | 26.67 |
| bust_in_display | 3,791 | 14.47 |
| cupsize_display | 2,578 | 9.84 |
| waist_in | 1,657 | 6.32 |
| hips_in_display | 1,278 | 4.88 |
| bust_in_number_display | 1,260 | 4.81 |
| bra_band_in_display | 680 | 2.6 |

## Early Prospecting Gaps

- bra band 40+: 29 rows (0.14% of usable rows). Target: Full-bust and plus lingerie sites.
- hips 48+ in: 123 rows (0.6% of usable rows). Target: Curve denim/swim/activewear where reviewers state hip measurements.
- waist 40+ in: 132 rows (0.65% of usable rows). Target: Curve denim, shapewear, plus workwear, plus formalwear.
- bust 44+ in: 149 rows (0.73% of usable rows). Target: Full-bust swim, dresses, bras, and bust-friendly apparel.
- very high weight (260+ lb): 220 rows (1.08% of usable rows). Target: Dedicated extended plus and inclusive sizing retailers.
- very tall height (6'0+): 302 rows (1.48% of usable rows). Target: Tall-focused brands and communities with reviewer measurements.
- very petite height (<5'0): 558 rows (2.74% of usable rows). Target: Petite-specialty retailers, short inseam denim, petite formalwear.
- low weight (<110 lb): 715 rows (3.51% of usable rows). Target: Petite/XXS brands with explicit reviewer stats.
- tall height (5'10+): 939 rows (4.61% of usable rows). Target: Tall-size shops, tall denim, long torso swim/activewear.
- cup DD+: 942 rows (4.63% of usable rows). Target: Full-bust bra/swim retailers with structured review fields.
- higher weight (200+ lb): 1,482 rows (7.28% of usable rows). Target: Plus-size, curve, shapewear, extended-size brands with photo reviews.

## Files

- `field_presence_summary.csv`
- `undercovered_segments.csv`
- `height_bins.csv`, `weight_bins.csv`, and body-measurement bin CSVs
- `height_x_weight_bins.csv`
- `charts/*.svg`
