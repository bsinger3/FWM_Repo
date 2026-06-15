# Measurement Coverage Snapshot

Generated: 2026-06-09 20:44:59 UTC

## Scope

- Unique rows scanned: 264,573
- Rows usable for body-size prospecting: 111,036
- Rows with both height and weight: 79,499
- Rows with any body-specific measurement beyond height/weight: 50,960

## Source Mix

- cv_gated_all: 225,947
- human_labeled: 37,626
- ready_labeled_source: 933
- ready_human_approved: 67

Input rows before dedupe:

- cv_gated_all / cv_gate_checkpoint_parts: 324,201
- unprocessed / unprocessed_not_cv_or_human: 154,201
- human_labeled / human_labeled_returns: 37,718
- ready_labeled_source / ready_labeled_source: 3,000
- ready_human_approved / ready_human_approved: 1,761

## Coverage By Field

| field | rows_with_value | pct_of_unique_rows |
| --- | ---: | ---: |
| size_display | 264,573 | 100.0 |
| height_in_display | 239,894 | 90.67 |
| weight_lbs_display | 95,181 | 35.98 |
| bust_in_display | 31,869 | 12.05 |
| cupsize_display | 29,176 | 11.03 |
| bra_band_in_display | 20,906 | 7.9 |
| bust_in_number_display | 14,258 | 5.39 |
| inseam_inches_display | 12,394 | 4.68 |
| waist_in | 10,312 | 3.9 |
| hips_in_display | 9,110 | 3.44 |

## Early Prospecting Gaps

- bra band 40+: 1,455 rows (1.31% of usable rows). Target: Full-bust and plus lingerie sites.
- very tall height (6'0+): 1,605 rows (1.45% of usable rows). Target: Tall-focused brands and communities with reviewer measurements.
- hips 48+ in: 2,073 rows (1.87% of usable rows). Target: Curve denim/swim/activewear where reviewers state hip measurements.
- waist 40+ in: 2,169 rows (1.95% of usable rows). Target: Curve denim, shapewear, plus workwear, plus formalwear.
- very high weight (260+ lb): 2,274 rows (2.05% of usable rows). Target: Dedicated extended plus and inclusive sizing retailers.
- bust 44+ in: 2,462 rows (2.22% of usable rows). Target: Full-bust swim, dresses, bras, and bust-friendly apparel.
- tall height (5'10+): 4,772 rows (4.3% of usable rows). Target: Tall-size shops, tall denim, long torso swim/activewear.
- very petite height (<5'0): 6,558 rows (5.91% of usable rows). Target: Petite-specialty retailers, short inseam denim, petite formalwear.
- cup DD+: 8,385 rows (7.55% of usable rows). Target: Full-bust bra/swim retailers with structured review fields.
- higher weight (200+ lb): 9,295 rows (8.37% of usable rows). Target: Plus-size, curve, shapewear, extended-size brands with photo reviews.
- low weight (<110 lb): 22,225 rows (20.02% of usable rows). Target: Petite/XXS brands with explicit reviewer stats.

## Files

- `field_presence_summary.csv`
- `undercovered_segments.csv`
- `height_bins.csv`, `weight_bins.csv`, and body-measurement bin CSVs
- `height_x_weight_bins.csv`
- `charts/*.svg`
