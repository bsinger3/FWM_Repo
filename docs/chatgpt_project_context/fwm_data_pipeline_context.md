---
context_file: fwm_data_pipeline_context
created_at: 2026-05-20
last_updated_at: 2026-05-20
source_workspace: /Users/briannasinger/Projects/ChatHistory
intended_project: Friends With Measurements
staleness_note: This file reflects project state as of 2026-05-20 and may become outdated as data pipelines, Supabase schemas, scraping workflows, image sorting models, or product priorities change.
---

# FWM Data And Pipeline Context

## Repository And Data Layout

Keep source code, lightweight docs, schema, and app files in `FWM_Repo`. Keep raw scraped data, intermediate outputs, publish-ready exports, review workbooks, and local model files outside the repo in `FWM_Data`.

Known local data paths:

- Mac: `/Users/briannasinger/Projects/FWM/FWM_Data`
- Windows: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data`

Recommended data layout:

```text
FWM_Data/
  amazon/
    data/
    models/
  non-amazon/
    data/
  models/
```

The repo may keep symlinks at `data-pipelines/amazon/data`, `data-pipelines/amazon/models`, and `data-pipelines/non-amazon/data`, but the real files should live in `FWM_Data`.

## Scrape Handoff Requirements

Every scrape handoff should report counts for:

- Rows with a distinct product URL.
- Rows with at least one body measurement.
- Rows with a customer/review image.
- Rows with the ordered size.
- Rows satisfying all four requirements for Supabase insertion.

Do not drop rows solely because size or measurement extraction failed during an early raw scrape. Keep rows that have a user comment/review body, because deterministic functions may later extract measurements from the comment text. Keep rows that expose the size ordered for the same reason: ordered-size extraction may be repairable after the raw scrape. Preserve enough raw context to repair the row later.

## Amazon Scraping

Amazon is currently the best source of review data for FWM because reviewers often report their measurements in the body of their comments, and Amazon does a good job associating the size ordered with each review.

We have not been able to scrape Amazon reliably using Codex prompts alone. Use Apify for Amazon scraping. There is an Apify subscription that gets turned on periodically when Amazon review data needs to be collected.

## Image Sorting And CV Triage

Image review is one of the biggest operational bottlenecks in the pipeline. There are too many scraped photos for fully manual sorting. The current direction is to use computer vision models to quickly separate obvious approvals, obvious rejections, and rows that still need manual review.

The Amazon Step 4 image workflow in `data-pipelines/amazon/scripts/step_4_human_review_and_visibility_decisions/` uses CV-enriched batches and rule-applied batches. The main rule library, `cv_rules_workflow_lib.py`, uses YOLO detect, YOLO pose, and YuNet face detection. Important CV fields include:

- `person_count_yolo_detect`
- `main_person_height_pct_yolo_detect`
- `main_person_bbox_area_pct_yolo_detect`
- `body_coverage_score_yolo_pose`
- `has_face_yunet`
- `cv_decision`
- `cv_reason_code`
- `cv_reason_summary`

Current rule decisions are `APPROVE`, `REJECT`, and `REVIEW`. Obvious rejects include no person, multiple people, too little body visible, the subject too small, or a small/distant subject with no detected face. Obvious approvals require one person, strong framing, enough body visible, and enough subject area. Borderline body coverage, borderline subject size, missing CV data, and ambiguous composition go to manual review.

This is useful but not enough. There is more research to do on additional computer vision and multimodal models that can identify catalog-style/product-only images, determine whether the reviewed garment is actually visible, evaluate crop usefulness for fit, detect duplicates, and reduce the manual review queue.

## Product Metadata And Category Assignment

The preferred product-category evidence order is:

1. Product metadata from the retailer page, such as title, subtitle, product type, description, and detail bullets.
2. Rich product URL slug.
3. Existing trusted `clothing_type_id`.
4. Review text only as a fallback or supporting signal.

Important product/category fields mentioned across repo docs and transcript work:

- `clothing_type_id`
- `product_page_url_display`
- `monetized_product_url_display`
- `original_url_display`
- `size_display`
- `source_site_display`
- `match_by_measurements`

## Backup And Restore

FWM data is backed up to a private S3 bucket. Use the dedicated AWS profile `fwm` and do not use root AWS credentials for normal sync work.

Relevant local environment variables in the FWM repo:

```text
FWM_DATA_DIR=...
FWM_S3_BUCKET=...
FWM_AWS_PROFILE=fwm
```

## Supabase Transcript Memory

FWM ChatGPT export rows are now in the existing dev transcript table:

- Table: `codex_chat_transcripts`
- Source label for these rows: `chatgpt_export`
- Project metadata: `friends_with_measurements`
- Count: `252`

Pipeline-related uploaded chats:

| Date | Title | Confidence | Chat Key | Evidence |
| --- | --- | ---: | --- | --- |
| 2026-04-29 | Data Product Manager Story | 0.99 | `fwm-chatgpt-69f23ecd-1df0-8329-85ea-522e088803ac` | friendswithmeasurements.com, FWM_Repo, match_by_measurements, original_url_display |
| 2026-04-24 | Google Drive Folder Access | 0.99 | `fwm-chatgpt-69ebb413-f1e0-83ea-ae2f-c53cb5d78569` | Friends With Measurements, Friends with Measurements, FWM, review images |
| 2026-04-23 | Reddit URL for Apify | 0.99 | `fwm-chatgpt-69ea55ff-49b4-83ea-8313-e1248d419254` | FWM, Apify, height |
| 2026-04-23 | LLM-native Web Scraping Tools | 0.99 | `fwm-chatgpt-69ea5195-ea34-83ea-9017-8f7db5e02b0d` | FWM_Data, FWM_Repo, FWM, scrape reviews |
| 2026-04-15 | Google Sheets API Integration | 0.99 | `fwm-chatgpt-69deed1f-8a7c-83ea-b417-8304b0b5bb31` | monetized_product_url_display, original_url_display, product_page_url_display, product URL |
| 2026-04-15 | Bra Review Websites | 0.75 | `fwm-chatgpt-69deeca7-e0a8-83ea-920f-3078489a1074` | review images, bust |
| 2026-04-10 | Monetized Link Generation | 0.99 | `fwm-chatgpt-69d88420-ad64-8330-9964-f94d0cf59830` | FWM_Repo, monetized_product_url_display, product_page_url_display, FWM |
| 2026-04-09 | Yotpo Review API Extraction | 0.93 | `fwm-chatgpt-69d7edda-0290-8328-9882-f1e66ceebda4` | FWM, scrape reviews |
| 2026-04-07 | File Access Request | 0.99 | `fwm-chatgpt-69d489fa-dff4-832f-9663-74884e19612a` | friendswithmeasurements.com, FWM_Repo, clothing_type_id, monetized_product_url_display |
| 2026-04-07 | DBeaver CSV Normalization | 0.99 | `fwm-chatgpt-69d47bee-54a4-832c-83fb-89ada082d94c` | friendswithmeasurements.com, FWM_Repo, FWM, fit matching |
| 2026-04-07 | Google Drive File Access | 0.99 | `fwm-chatgpt-69d47664-1538-832b-a6cb-1019c815766e` | friendswithmeasurements.com, FWM_Repo, FWM, customer image |
| 2026-04-03 | Amazon Reviewer Profiles Analysis | 0.99 | `fwm-chatgpt-69cf1291-919c-832c-bb28-4b61bbcea7cb` | friendswithmeasurements.com, FWM, body measurements, Amazon review |
| 2026-03-27 | Codex CLI CSV Conversion | 0.99 | `fwm-chatgpt-69c6c1ea-ada0-8332-88e6-ba4428d3ed69` | FWM_Repo, clothing_type_id, monetized_product_url_display, original_url_display |
| 2026-03-26 | DBeaver Installation Guide | 0.99 | `fwm-chatgpt-69c56282-5490-8328-85ee-c4adcbcd60b5` | FWM_Repo, match_by_measurements, clothing_type_id, monetized_product_url_display |
| 2026-03-24 | Supabase anon key update | 0.99 | `fwm-chatgpt-69c2f2f2-f718-832e-8726-21b3320fe463` | Friends With Measurements, Friends with Measurements, FWM_Repo, match_by_measurements |
| 2026-03-20 | Codex App vs CLI | 0.99 | `fwm-chatgpt-69bcc673-8aa4-8329-b6ba-eacee34e418c` | clothing_type_id, monetized_product_url_display, original_url_display, product_page_url_display |
| 2026-03-16 | Incell formula for size | 0.99 | `fwm-chatgpt-69b8550b-c214-8331-9990-d348cf7ebae3` | FWM_Repo, FWM, Amazon reviews, bust |
| 2026-03-16 | Images Table Columns | 0.99 | `fwm-chatgpt-69b8536d-abac-8329-ae40-5e0cb9bca2ba` | FWM_Repo, monetized_product_url_display, original_url_display, product_page_url_display |
| 2026-03-16 | AI Data Normalization Plan | 0.99 | `fwm-chatgpt-69b85026-0db8-8325-9070-90725b7cb206` | friendswithmeasurements.com, FWM_Repo, FWM, product URL |
| 2026-03-16 | Image Search Function | 0.99 | `fwm-chatgpt-69b84b38-d214-8332-9e28-69973ee7338e` | FWM_Repo, monetized_product_url_display, original_url_display, product_page_url_display |
| 2026-03-12 | Images Data Normalization | 0.99 | `fwm-chatgpt-69b319f4-d22c-832f-ba45-b1b9492b1afb` | FWM_Repo, clothing_type_id, monetized_product_url_display, original_url_display |
| 2026-03-12 | Fixing Broken Links | 0.99 | `fwm-chatgpt-69b231b2-70f4-8333-b2cb-0c0b4bdfb620` | FWM_Repo, monetized_product_url_display, original_url_display, product_page_url_display |
| 2026-02-26 | GAS Plan for Octoparse Data | 0.99 | `fwm-chatgpt-699fb7db-04f8-8330-8ba7-822d488142ff` | FWM_Repo, clothing_type_id, monetized_product_url_display, original_url_display |
| 2026-02-24 | Tracking User Activity | 0.99 | `fwm-chatgpt-699dd8b3-25fc-832e-a830-b771b0df766c` | Friends With Measurements, Friends with Measurements, friendswithmeasurements.com, FWM_Repo |
