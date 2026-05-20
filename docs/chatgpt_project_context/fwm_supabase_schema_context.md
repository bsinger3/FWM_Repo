---
context_file: fwm_supabase_schema_context
created_at: 2026-05-20
last_updated_at: 2026-05-20
source_workspace: /Users/briannasinger/Projects/ChatHistory
intended_project: Friends With Measurements
staleness_note: This file reflects project state as of 2026-05-20 and may become outdated as data pipelines, Supabase schemas, scraping workflows, image sorting models, or product priorities change.
---

# FWM Supabase Schema Context

## Scope And Sources

This is the app-dev schema reference for Friends With Measurements. The existing context docs did not fully enumerate every Supabase table, column, relationship, and RPC, so this file should be added to the FWM ChatGPT project alongside the other FWM context files.

Sources used:

- Generated Supabase types: `/Users/briannasinger/Projects/FWM/FWM_Repo/database.types.ts`
- Public migrations: `/Users/briannasinger/Projects/FWM/FWM_Repo/supabase/migrations`
- Dev migrations: `/Users/briannasinger/Projects/FWM/FWM_Repo/supabase/dev-migrations`

Treat this file as a snapshot from 2026-05-20. Before destructive migrations, production writes, or broad data backfills, verify against the live Supabase project.

## App-Facing Schema Summary

- Primary app table: `public.images`
- Category lookup table: `public.clothing_types`
- Search analytics table: `public.search_events`
- Product-card analytics table: `public.product_card_events`
- Transcript memory table: `public.codex_chat_transcripts`
- Backup/staging public tables: `public.images_backup_20260320`, `public.images_staging`, `public."archive.images_backup_20260320_063904"`
- Public view: `public.product_card_ctr_daily`
- Main app RPC: `public.match_by_measurements`
- Private product-category enrichment schema: `staging`

## Public Tables

### `public."archive.images_backup_20260320_063904"`

| Column | Type |
| --- | --- |
| `age_raw` | `string \| null` |
| `age_years_display` | `number \| null` |
| `brand` | `string \| null` |
| `bust_in_number_display` | `number \| null` |
| `bytes` | `string \| null` |
| `clothing_type_id` | `string \| null` |
| `color_canonical` | `string \| null` |
| `color_display` | `string \| null` |
| `content_type` | `string \| null` |
| `created_at_display` | `string \| null` |
| `cupsize_display` | `string \| null` |
| `date_review_submitted_raw` | `string \| null` |
| `fetched_at` | `string \| null` |
| `hash_md5` | `string \| null` |
| `height` | `string \| null` |
| `height_in_display` | `number \| null` |
| `height_raw` | `string \| null` |
| `hips_in_display` | `number \| null` |
| `hips_raw` | `string \| null` |
| `id` | `string \| null` |
| `inseam_inches_display` | `number \| null` |
| `monetized_product_url_display` | `string \| null` |
| `original_url_display` | `string \| null` |
| `product_page_url_display` | `string \| null` |
| `review_date` | `string \| null` |
| `reviewer_name_raw` | `string \| null` |
| `reviewer_profile_url` | `string \| null` |
| `search_fts` | `string \| null` |
| `size_display` | `string \| null` |
| `source_site_display` | `string \| null` |
| `status_code` | `string \| null` |
| `updated_at` | `string \| null` |
| `user_comment` | `string \| null` |
| `waist_in` | `string \| null` |
| `waist_raw_display` | `string \| null` |
| `weight_display_display` | `string \| null` |
| `weight_lb` | `string \| null` |
| `weight_lbs_display` | `number \| null` |
| `weight_lbs_raw_issue` | `string \| null` |
| `weight_raw` | `string \| null` |
| `weight_raw_needs_correction` | `string \| null` |
| `width` | `string \| null` |

Relationships:
- None declared in generated types.

### `public.clothing_types`

| Column | Type |
| --- | --- |
| `id` | `string` |
| `label` | `string` |
| `sort_order` | `number` |

Relationships:
- None declared in generated types.

### `public.codex_chat_transcripts`

| Column | Type |
| --- | --- |
| `chat_key` | `string` |
| `context_summary` | `string \| null` |
| `context_summary_json` | `Json` |
| `created_at` | `string` |
| `full_text` | `string` |
| `id` | `string` |
| `local_file_path` | `string \| null` |
| `message_count` | `number` |
| `source` | `string` |
| `title` | `string \| null` |
| `transcript_ended_at` | `string \| null` |
| `transcript_started_at` | `string \| null` |
| `transcript_json` | `Json` |
| `updated_at` | `string` |

Relationships:
- None declared in generated types.

### `public.images`

| Column | Type |
| --- | --- |
| `age_raw` | `string \| null` |
| `age_years_display` | `number \| null` |
| `brand` | `string \| null` |
| `bust_in_number_display` | `number \| null` |
| `bytes` | `string \| null` |
| `clothing_type_id` | `string \| null` |
| `color_canonical` | `string \| null` |
| `color_display` | `string \| null` |
| `content_type` | `string \| null` |
| `created_at_display` | `string` |
| `cupsize_display` | `string \| null` |
| `date_review_submitted_raw` | `string \| null` |
| `fetched_at` | `string \| null` |
| `hash_md5` | `string \| null` |
| `height` | `string \| null` |
| `height_in_display` | `number \| null` |
| `height_raw` | `string \| null` |
| `hips_in_display` | `number \| null` |
| `hips_raw` | `string \| null` |
| `id` | `string` |
| `inseam_inches_display` | `number \| null` |
| `monetized_product_url_display` | `string \| null` |
| `original_url_display` | `string \| null` |
| `product_page_url_display` | `string \| null` |
| `review_date` | `string \| null` |
| `reviewer_name_raw` | `string \| null` |
| `reviewer_profile_url` | `string \| null` |
| `search_fts` | `string \| null` |
| `size_display` | `string` |
| `source_site_display` | `string \| null` |
| `status_code` | `string \| null` |
| `updated_at` | `string \| null` |
| `user_comment` | `string \| null` |
| `waist_in` | `string \| null` |
| `waist_raw_display` | `string \| null` |
| `weight_display_display` | `string \| null` |
| `weight_lb` | `string \| null` |
| `weight_lbs_display` | `number \| null` |
| `weight_lbs_raw_issue` | `string \| null` |
| `weight_raw` | `string \| null` |
| `weight_raw_needs_correction` | `string \| null` |
| `width` | `string \| null` |

Relationships:
- `clothing_type_id` -> `public.clothing_types.id` via `images_clothing_type_fk`.

### `public.images_backup_20260320`

| Column | Type |
| --- | --- |
| `age_raw` | `string \| null` |
| `age_years_display` | `number \| null` |
| `brand` | `string \| null` |
| `bust_in_number_display` | `number \| null` |
| `bytes` | `string \| null` |
| `clothing_type_id` | `string \| null` |
| `color_canonical` | `string \| null` |
| `color_display` | `string \| null` |
| `content_type` | `string \| null` |
| `created_at_display` | `string \| null` |
| `cupsize_display` | `string \| null` |
| `date_review_submitted_raw` | `string \| null` |
| `fetched_at` | `string \| null` |
| `hash_md5` | `string \| null` |
| `height` | `string \| null` |
| `height_in_display` | `number \| null` |
| `height_raw` | `string \| null` |
| `hips_in_display` | `number \| null` |
| `hips_raw` | `string \| null` |
| `id` | `string \| null` |
| `inseam_inches_display` | `number \| null` |
| `monetized_product_url_display` | `string \| null` |
| `original_url_display` | `string \| null` |
| `product_page_url_display` | `string \| null` |
| `review_date` | `string \| null` |
| `reviewer_name_raw` | `string \| null` |
| `reviewer_profile_url` | `string \| null` |
| `search_fts` | `string \| null` |
| `size_display` | `string \| null` |
| `source_site_display` | `string \| null` |
| `status_code` | `string \| null` |
| `updated_at` | `string \| null` |
| `user_comment` | `string \| null` |
| `waist_in` | `string \| null` |
| `waist_raw_display` | `string \| null` |
| `weight_display_display` | `string \| null` |
| `weight_lb` | `string \| null` |
| `weight_lbs_display` | `number \| null` |
| `weight_lbs_raw_issue` | `string \| null` |
| `weight_raw` | `string \| null` |
| `weight_raw_needs_correction` | `string \| null` |
| `width` | `string \| null` |

Relationships:
- None declared in generated types.

### `public.images_staging`

| Column | Type |
| --- | --- |
| `age_raw` | `string \| null` |
| `age_years_display` | `number \| null` |
| `brand` | `string \| null` |
| `bust_in_number_display` | `number \| null` |
| `bytes` | `string \| null` |
| `clothing_type_id` | `string \| null` |
| `color_canonical` | `string \| null` |
| `color_display` | `string \| null` |
| `content_type` | `string \| null` |
| `created_at_display` | `string \| null` |
| `cupsize_display` | `string \| null` |
| `date_review_submitted_raw` | `string \| null` |
| `fetched_at` | `string \| null` |
| `hash_md5` | `string \| null` |
| `height` | `string \| null` |
| `height_in_display` | `number \| null` |
| `height_raw` | `string \| null` |
| `hips_in_display` | `number \| null` |
| `hips_raw` | `string \| null` |
| `id` | `string \| null` |
| `inseam_inches_display` | `number \| null` |
| `monetized_product_url_display` | `string \| null` |
| `original_url_display` | `string \| null` |
| `product_page_url_display` | `string \| null` |
| `review_date` | `string \| null` |
| `reviewer_name_raw` | `string \| null` |
| `reviewer_profile_url` | `string \| null` |
| `search_fts` | `string \| null` |
| `size_display` | `string \| null` |
| `source_site_display` | `string \| null` |
| `status_code` | `string \| null` |
| `updated_at` | `string \| null` |
| `user_comment` | `string \| null` |
| `waist_in` | `string \| null` |
| `waist_raw_display` | `string \| null` |
| `weight_display_display` | `string \| null` |
| `weight_lb` | `string \| null` |
| `weight_lbs_display` | `number \| null` |
| `weight_lbs_raw_issue` | `string \| null` |
| `weight_raw` | `string \| null` |
| `weight_raw_needs_correction` | `string \| null` |
| `width` | `string \| null` |

Relationships:
- None declared in generated types.

### `public.product_card_events`

| Column | Type |
| --- | --- |
| `anon_id` | `string` |
| `card_position` | `number \| null` |
| `created_at` | `string` |
| `event_type` | `Database["public"]["Enums"]["product_card_event_type"]` |
| `id` | `string` |
| `image_id` | `string \| null` |
| `page_url` | `string \| null` |
| `product_url` | `string \| null` |
| `result_context` | `string` |
| `search_event_id` | `string \| null` |
| `session_id` | `string` |
| `source_site_display` | `string \| null` |

Relationships:
- `image_id` -> `public.images.id` via `product_card_events_image_id_fkey`.
- `search_event_id` -> `public.search_events.id` via `product_card_events_search_event_id_fkey`.

### `public.search_events`

| Column | Type |
| --- | --- |
| `anon_id` | `string` |
| `bust_in` | `number \| null` |
| `clothing_type` | `string \| null` |
| `created_at` | `string` |
| `feet` | `number \| null` |
| `hips_in` | `number \| null` |
| `id` | `string` |
| `inches` | `number \| null` |
| `latency_ms` | `number \| null` |
| `page_url` | `string \| null` |
| `referrer` | `string \| null` |
| `results_count` | `number \| null` |
| `session_id` | `string` |
| `utm_campaign` | `string \| null` |
| `utm_content` | `string \| null` |
| `utm_medium` | `string \| null` |
| `utm_source` | `string \| null` |
| `weight_lb` | `number \| null` |

Relationships:
- None declared in generated types.


## Public Views

### `public.product_card_ctr_daily`

| Column | Type |
| --- | --- |
| `clicks` | `number \| null` |
| `click_through_rate` | `number \| null` |
| `event_date` | `string \| null` |
| `impressions` | `number \| null` |
| `view_click_through_rate` | `number \| null` |
| `views` | `number \| null` |


## Public Relationships

| From | To | Constraint |
| --- | --- | --- |
| `public.images.clothing_type_id` | `public.clothing_types.id` | `images_clothing_type_fk` |
| `public.product_card_events.image_id` | `public.images.id` | `product_card_events_image_id_fkey` |
| `public.product_card_events.search_event_id` | `public.search_events.id` | `product_card_events_search_event_id_fkey` |

## Public Enums

| Enum | Values |
| --- | --- |
| `product_card_event_type` | `"impression" \| "view" \| "click"` |

## Public RPCs

| RPC | Arguments | Returns | Notes |
| --- | --- | --- | --- |
| `public.format_weight_display` | `p_weight_lb: number`, `p_weight_raw: string` | string | Deterministic parsing/formatting helper. |
| `public.host_name` | `u: string` | string |  |
| `public.get_distinct_cup_sizes` | `limit_n?: number`, `prefix_text?: string` | rows: `cup_size` | Autocomplete/filter helper. |
| `public.inspect_table_columns_examples` | `example_limit?: number`, `in_schema: string`, `in_table: string` | rows: `character_maximum_length`, `column_name`, `data_type`, `distinct_count`, `examples`, `is_nullable`, `max_value`, `min_value` |  |
| `public.match_by_measurements` | `in_bust?: number`, `in_cup_size?: string`, `in_clothing_type_id?: string`, `in_height?: number`, `in_hips?: number`, `in_waist?: number`, `in_weight?: number`, `limit_n?: number`, `offset_n?: number`, `require_bust?: boolean`, `require_height?: boolean`, `require_hips?: boolean`, `require_waist?: boolean`, `require_weight?: boolean` | rows: `age_years_display`, `brand`, `bust_in_number_display`, `color_display`, `cupsize_display`, `height_in_display`, `id`, `inseam_inches_display`, `monetized_product_url_display`, `original_url_display`, `product_page_url_display`, `size_display`, `source_site_display`, `waist_in`, `weight_display_display`, `hips_in_display` | Primary frontend search RPC. Supports optional measurement filters and boolean require flags. |
| `public.match_by_measurements_deprecated` | overload 1: `in_bust?: number`, `in_height?: number`, `in_hips?: number`, `in_waist?: number`, `in_weight?: number`, `limit_n?: number`, `offset_n?: number`<br>overload 2: `color_raw?: string`, `in_bust?: number`, `in_height?: number`, `in_hips?: number`, `in_waist?: number`, `in_weight?: number`, `limit_n?: number`, `offset_n?: number`, `retailer?: string`, `size_raw?: string` | 2 row-shape overloads; see generated type for exact deprecated return columns | Deprecated; keep for historical compatibility only. |
| `public.parse_age_years` | `t: string` | number | Deterministic parsing/formatting helper. |
| `public.parse_height_in` | `t: string` | number | Deterministic parsing/formatting helper. |
| `public.parse_inches` | `t: string` | number | Deterministic parsing/formatting helper. |
| `public.parse_weight_lb` | `t: string` | number | Deterministic parsing/formatting helper. |
| `public.search_catalog_deprecated` | `color_raw?: string`, `end_date?: string`, `limit_n?: number`, `max_height?: number`, `min_height?: number`, `offset_n?: number`, `q?: string`, `retailer?: string`, `size_raw?: string`, `start_date?: string` | unknown[] | Deprecated; keep for historical compatibility only. |
| `public.show_limit` | `none` | number |  |
| `public.show_trgm` | `arg: string` | string[] |  |
| `public.update_search_event_metrics` | `p_id: string`, `p_latency_ms: number`, `p_results_count: number` | undefined | Analytics update helper for search events. |

## Staging Schema

The `staging` schema is private and intended for product-level category/tag enrichment. It is not used directly by the live website. The migration revokes public access and grants usage to `postgres` and `service_role`.

### `staging.clothing_mother_categories`

| Column | Type |
| --- | --- |
| `id` | `text, primary key` |
| `label` | `text, not null` |
| `display_label` | `text, not null` |
| `sort_order` | `integer, default 999` |
| `frontend_sort_order` | `integer, default 999` |
| `is_frontend_filter` | `boolean, default true` |
| `created_at` | `timestamptz, default now()` |
| `updated_at` | `timestamptz, default now()` |

### `staging.clothing_type_tags`

| Column | Type |
| --- | --- |
| `id` | `text, primary key` |
| `mother_category_id` | `text, references staging.clothing_mother_categories(id)` |
| `label` | `text, not null` |
| `display_label` | `text, not null` |
| `aliases` | `text[], default '{}'` |
| `sort_order` | `integer, default 999` |
| `frontend_sort_order` | `integer, default 999` |
| `is_search_tag` | `boolean, default true` |
| `is_frontend_filter` | `boolean, default true` |
| `search_boost` | `numeric, default 1` |
| `created_at` | `timestamptz, default now()` |
| `updated_at` | `timestamptz, default now()` |

### `staging.product_pages`

| Column | Type |
| --- | --- |
| `id` | `uuid, primary key, default gen_random_uuid()` |
| `normalized_product_page_url` | `text, unique, not null` |
| `source_site` | `text` |
| `brand` | `text` |
| `product_title_raw` | `text` |
| `product_category_raw` | `text` |
| `mother_category_id` | `text, references staging.clothing_mother_categories(id)` |
| `category_confidence` | `text, default low, check high/medium/low` |
| `category_evidence` | `text` |
| `needs_manual_review` | `boolean, default true` |
| `observed_clothing_type_ids` | `text[], default '{}'` |
| `image_row_count` | `integer, default 0` |
| `first_seen_at` | `timestamptz` |
| `last_seen_at` | `timestamptz` |
| `populated_from` | `text, default public.images` |
| `raw_metadata` | `jsonb, default '{}'` |
| `classified_at` | `timestamptz, default now()` |
| `created_at` | `timestamptz, default now()` |
| `updated_at` | `timestamptz, default now()` |

### `staging.product_page_clothing_type_tags`

| Column | Type |
| --- | --- |
| `product_page_id` | `uuid, references staging.product_pages(id) on delete cascade` |
| `clothing_type_id` | `text, references staging.clothing_type_tags(id)` |
| `evidence` | `text` |
| `created_at` | `timestamptz, default now()` |
| `primary key` | `(product_page_id, clothing_type_id)` |

### `staging.product_page_image_sources`

| Column | Type |
| --- | --- |
| `product_page_id` | `uuid, references staging.product_pages(id) on delete cascade` |
| `image_id` | `uuid, public.images row id but no FK declared` |
| `original_product_page_url` | `text` |
| `original_monetized_product_url` | `text` |
| `source_site` | `text` |
| `brand` | `text` |
| `clothing_type_id` | `text` |
| `created_at_display` | `timestamptz` |
| `created_at` | `timestamptz, default now()` |
| `primary key` | `(product_page_id, image_id)` |


### Staging Relationships

| From | To |
| --- | --- |
| `staging.clothing_type_tags.mother_category_id` | `staging.clothing_mother_categories.id` |
| `staging.product_pages.mother_category_id` | `staging.clothing_mother_categories.id` |
| `staging.product_page_clothing_type_tags.product_page_id` | `staging.product_pages.id` |
| `staging.product_page_clothing_type_tags.clothing_type_id` | `staging.clothing_type_tags.id` |
| `staging.product_page_image_sources.product_page_id` | `staging.product_pages.id` |

### Staging RPCs

| RPC | Arguments | Returns | Notes |
| --- | --- | --- | --- |
| `staging.normalize_product_url` | `raw_url text` | `text` | Lowercases, strips fragments/query strings/trailing slashes, returns null for blank input. |
| `staging.category_from_product_signal` | `normalized_product_page_url text`, `observed_clothing_type_ids text[] default '{}'` | `mother_category_id`, `clothing_type_tag_ids`, `category_confidence`, `category_evidence`, `needs_manual_review` | Infers mother category and tags from product URL and observed image clothing type ids. |
| `staging.refresh_product_category_staging` | `none` | `product_pages_inserted`, `tag_links_inserted`, `image_links_inserted`, `low_confidence_products` | Rebuilds staging product-category rollups from `public.images`. |
| `staging.infer_product_title_from_url` | `normalized_product_page_url text` | `text` | Added by later staging tightening migration; derives a title-like string from the URL. |
| `staging.infer_brand_from_product_url` | `normalized_product_page_url text` | `text` | Added by later staging tightening migration; derives brand/source signal from the URL. |

## App Development Notes

Use `public.match_by_measurements` for fit-search results rather than selecting directly from `public.images` when implementing user search. It returns the display-oriented fields the frontend expects, including image URL, product URL, size, source site, brand, color, and body-measurement fields.

Use `public.get_distinct_cup_sizes` for cup-size picker/autocomplete behavior. Use `public.search_events` and `public.product_card_events` for analytics rather than adding tracking columns to `public.images`.

`public.images_staging` and the backup tables should not be treated as canonical app data. They are useful for migrations, repair, and recovery, but app reads should prefer `public.images` unless a task explicitly says otherwise.

`public.codex_chat_transcripts` is a project-memory table. FWM ChatGPT export rows are labeled with `source = 'chatgpt_export'` and `context_summary_json->>project = 'friends_with_measurements'`.
