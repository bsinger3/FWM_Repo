# Bloomingdale's AQUA Conversion Notes - 2026-05-05

## Status

- Retailer: `bloomingdales_aqua`
- Source: local workbook `Bloomingdales_Aqua.xlsx`
- Claim: `_active_scrape_claims/bloomingdales_aqua.claim`
- Current status: `completed_from_workbook_review_photo_sheet`

## Outcome

- Added `convert_bloomingdales_aqua_workbook.py`.
- Converted existing Bazaarvoice review-photo workbook rows into the current Step 1 intake schema.
- No live site requests were made.
- Output after duplicate cleanup:
  - Rows: 399
  - Distinct images: 175
  - Distinct products: 201
  - Rows with ordered size: 285
  - Rows with any measurement: 177
  - Supabase-qualified rows: 166

## Notes

- The workbook repeats the same `BigImage` / `Page_URL` values across multiple extracted column groups.
- The converter generates stable review IDs from product URL, image URL, comment, size, and profile text so exact duplicates collapse while keeping distinct size/profile variants.
- Product title and brand context come from the workbook `ProductLiks` sheet.

## Revisit Plan

- Revisit only if a newer workbook or a safe public Bazaarvoice media endpoint becomes available.
- If revisited, inspect duplicate patterns before counting rows.
