---
context_file: fwm_project_context
created_at: 2026-05-20
last_updated_at: 2026-05-20
source_workspace: /Users/briannasinger/Projects/ChatHistory
intended_project: Friends With Measurements
staleness_note: This file reflects project state as of 2026-05-20 and may become outdated as data pipelines, Supabase schemas, scraping workflows, image sorting models, or product priorities change.
---

# Friends With Measurements Project Context

## How To Use These Context Files

Use this file as the main scope-of-work and project context file for the Friends With Measurements ChatGPT project.

Use `fwm_data_pipeline_context.md` for scraping, data layout, Amazon/Apify, and image sorting details. Use `fwm_supabase_schema_context.md` for app-dev Supabase table, column, relationship, view, enum, and RPC reference. Use `fwm_chatgpt_transcript_memory.md` only when you need to locate prior ChatGPT conversations by `chat_key`. Prefer these context docs over raw transcript memory unless a specific prior chat is needed.

Treat the dates at the top of each file as freshness markers. If a file is older than the current pipeline work, verify details against the FWM repo and Supabase before acting.

## Product Summary

Friends With Measurements is a project about clothing fit, sizing, and measurements. The product helps shoppers understand how clothes fit on real people by pairing public retailer review photos with structured sizing and body-measurement context.

The live site is `friendswithmeasurements.com`. The GitHub repository is `FWM_Repo`. The static frontend is hosted on Cloudflare Pages and served from raw HTML, JavaScript, and CSS without a build step.

## Core User Value

The central user problem is that online shoppers cannot tell how clothing will fit from generic product photos and size charts alone. FWM tries to make fit more concrete by showing shopper review images from people with similar measurements.

The strongest product framing from prior chats is:

- Help shoppers find clothing that fits using real product photos from people with similar body measurements.
- Preserve enough measurement and product-link context for each image to make the card useful and clickable.
- Treat fit evidence as a combination of image, ordered size, product page, review text, and body measurements.

## Collaboration Guidance

When helping with FWM, favor practical, implementation-ready answers that preserve data provenance and are careful about image usefulness, product-category ambiguity, and measurement extraction.

Be direct and precise. When drafting docs or implementation plans, include exact table names, column names, file paths, and validation checks. When drafting product copy or resume bullets, keep the language credible and concrete rather than inflated.

## Minimum Useful Card Data

An FWM image/card should have:

- A customer/review image URL, usually `original_url_display`.
- A valid ordered size, usually `size_display`, not blank and not `unknown`.
- At least one body measurement, such as height, weight, bust, waist, hips, or cup size.
- A product URL, usually `product_page_url_display` or `monetized_product_url_display`.
- A grounded clothing category, ideally from product metadata rather than review text alone.

## Important Product Boundaries

Use product URLs, product titles, and product metadata as the source of truth for what item is being reviewed. Review text can mention comparison garments and styling ideas, so it should not be the primary category source unless no other source exists.

For image usefulness, approve images that help a shopper judge how the reviewed clothing fits on a real body. Reject or route to review when the image is product-only, a flat-lay, a label/tag, a catalog image, too cropped, ambiguous about which product is being reviewed, or mismatched against the metadata.

## Image Sorting And Computer Vision

Image sorting is a major bottleneck. FWM has many more scraped/review photos than a human can reasonably inspect one by one, so a major forward-looking project is using computer vision to make triage much faster.

The current approach is not to rely on CV as a perfect final judge. It uses CV models and deterministic rules to narrow the pile into obvious yes, obvious no, and needs-manual-review groups. In the FWM repo, the Amazon Step 4 image review workflow uses YOLO detection, YOLO pose, and YuNet face detection signals such as person count, main-person height percentage, bounding-box area, pose/body coverage score, and face presence. The rule output is stored in fields like `cv_decision`, `cv_reason_code`, and `cv_reason_summary`, with decisions such as `APPROVE`, `REJECT`, and `REVIEW`.

Current CV rules can catch obvious failures such as no person, multiple people, very low body coverage, or a subject too small in frame. They can also identify clear passes with one well-framed person and enough body visible. Many images still land in `REVIEW`, and human-visible issues such as darkness, clutter, bad angle, crop quality, duplicate images, catalog-style uploads, and whether the reviewed garment is actually visible still need better modeling.

More research is needed into additional CV models and multimodal approaches that can detect catalog/product-only images, determine whether clothing is being worn, assess whether the reviewed product is visible, catch duplicates, and reduce the manual review burden without discarding useful fit evidence.

## Transcript Memory Now Available

The FWM Supabase transcript table now contains high-confidence ChatGPT export conversations in addition to Codex chats:

- Table: `codex_chat_transcripts`
- ChatGPT rows are labeled with `source = 'chatgpt_export'`
- Metadata filter: `context_summary_json->>project = 'friends_with_measurements'`
- Codex session transcript rows use their own Codex-oriented source labels.
- Current ChatGPT row count: `252`
- Chat keys are formatted as `fwm-chatgpt-<conversation_id>`

Recent uploaded FWM ChatGPT conversations:

| Date | Title | Confidence | Chat Key | Evidence |
| --- | --- | ---: | --- | --- |
| 2026-05-05 | FWM App Dev to Supabase | 0.93 | `fwm-chatgpt-69fa1ace-f240-832c-996a-cbfb9e70aca7` | FWM |
| 2026-05-04 | Experience Summary Calculation | 0.99 | `fwm-chatgpt-69f8c427-3e6c-8326-b252-f3f342672bbf` | friendswithmeasurements.com, body measurements, clothing that fits, height |
| 2026-05-01 | Redshift Experience Framing | 0.99 | `fwm-chatgpt-69f4d045-2c88-8332-b04c-b53a7dd0dae2` | friendswithmeasurements.com, FWM, body measurements, clothing that fits |
| 2026-05-01 | BI Portfolio Project Ideas | 0.93 | `fwm-chatgpt-69f4cec8-69dc-8329-8d46-e668be200372` | FWM, body measurements |
| 2026-04-30 | Coping with Interview Stress | 0.9 | `fwm-chatgpt-69f37a5d-7568-832a-ae3a-f530628ee1e0` | FWM |
| 2026-04-29 | Data Product Manager Story | 0.99 | `fwm-chatgpt-69f23ecd-1df0-8329-85ea-522e088803ac` | friendswithmeasurements.com, FWM_Repo, match_by_measurements, original_url_display |
| 2026-04-29 | Clothing Rental by Size | 0.99 | `fwm-chatgpt-69f22aa2-1b7c-8333-897d-59ff74cca874` | FWM_Repo, match_by_measurements, FWM, body measurements |
| 2026-04-29 | Clicky.so Hotkeys Setup | 0.9 | `fwm-chatgpt-69f227b2-6e4c-8329-bd3d-921ec37bb072` | FWM |
| 2026-04-28 | Interview Leverage and Story Selection | 0.99 | `fwm-chatgpt-69f12c5a-dc24-832f-af6e-1397b993ddae` | Friends With Measurements, Friends with Measurements, friendswithmeasurements.com |
| 2026-04-28 | BI and Data Tools | 0.9 | `fwm-chatgpt-69f00b8a-8010-8329-a7ed-5cc3c6dcc390` | FWM |
| 2026-04-28 | BigQuery vs PostgreSQL | 0.95 | `fwm-chatgpt-69f009e3-9740-8325-ad0e-ad126d96f163` | FWM, height, weight |
| 2026-04-27 | Business vs Consumer Pricing | 0.94 | `fwm-chatgpt-69efddce-6a9c-83ea-9a65-b782b6df122b` | FWM, height |
