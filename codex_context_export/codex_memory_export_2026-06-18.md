# Codex Memory And Context Export

Generated: 2026-06-18

```text
[2026-06-18] - You are working in `/Users/briannasinger/Projects/FWM`, especially `FWM_Repo` and `FWM_Data`.
[2026-06-18] - Your name appears in local paths as `briannasinger`; the S3 bucket is named `s3://fwm-scraping-data-briannasinger`.
[2026-06-18] - Your environment/timezone context for this repo session is `America/New_York`.
[2026-06-18] - You are doing frequent operational work in `/Users/briannasinger/Projects/FWM`, especially dev-only Supabase refreshes, taxonomy review throughput, image-review dashboards, mobile review batches, transcript archival, and data-pipeline cleanup.
[2026-06-18] - You want progress grounded in the actual repo and current artifacts, not abstract advice.
[2026-06-18] - You often pair planning with execution, but you separate those modes clearly.
[2026-06-18] - If you ask for a plan first or say not to edit yet, you expect inspection and a written plan before changes.
[2026-06-18] - Once implementation is approved, you prefer momentum: minimal pausing, concise approval gates, and continued execution instead of over-explaining stalls.
[2026-06-18] - You care a lot about safety boundaries and artifact hygiene.
[2026-06-18] - Production boundaries in FWM matter.
[2026-06-18] - Unrelated dirty files should stay untouched.
[2026-06-18] - Generated data should generally live outside Git.
[2026-06-18] - Transcript artifacts should stay out of the repo root.
[2026-06-18] - You use Codex across long-running workflows and want resumed/crashed chats recovered, archived, and continued cleanly.
[2026-06-18] - Outside FWM, ad-hoc notes show a stable resume preference: default to a polished, restrained, text-extractable one-page PDF unless you explicitly ask for another format.
[2026-06-18] - In FWM dev work, honor hard safety boundaries from the start: `dev-only`, no production Supabase, no live-site deploy, and no production migrations.
[2026-06-18] - If you ask for a plan first or say `Do not edit files yet`, stay in planning mode until you explicitly approve implementation.
[2026-06-18] - Default to dry-run-first for DB or promotion flows; show what would change, then pause before the first write.
[2026-06-18] - Leave unrelated dirty worktree files alone, especially live `_claims/*.claim` files from other threads.
[2026-06-18] - Keep approval prompts short, explicit, and tied to the next concrete action; you often ask to `pause as little as possible`.
[2026-06-18] - If you say a field is wrong, stop treating it as evidence.
[2026-06-18] - In this workflow, `clothing_type_id` / `observed_clothing_type_ids` should not drive Amazon taxonomy fixes.
[2026-06-18] - When you will approve later in a dashboard, bias toward collecting report-ready data now instead of forcing early writes.
[2026-06-18] - For image-review work, keep source workbooks immutable, write reviewed outputs as new files, and build targeted subset dashboards when you ask for a narrow slice.
[2026-06-18] - For mobile image-review batches, re-scan the current `human_labeled_returns` folder before excluding rows; do not assume older batches were actually sorted.
[2026-06-18] - Treat transcript archival as part of done for FWM handoffs and resumed chats; use the repo uploader with compact JSON outside the repo.
[2026-06-18] - For resume generation, default to a professional one-page PDF with restrained formatting and verify it is text-extractable.
[2026-06-18] - Start with `cwd` and the existing repo workflow before inventing anything.
[2026-06-18] - In FWM, existing workflow often means `scripts/upload-codex-chat-transcript.mjs`, dev Supabase guards, `supabase/dev-migrations`, and report writers under `FWM_Data/_reports`.
[2026-06-18] - On this Mac, Playwright/Chromium can fail with `bootstrap_check_in ... Permission denied (1100)` under sandboxing; unsandboxed reruns are the known fix.
[2026-06-18] - For transcript or Supabase readback snippets, avoid mixing `require` with top-level `await`; use an async IIFE or pure ESM.
[2026-06-18] - Reuse local skills first: `/Users/briannasinger/.codex/memories/skills/fwm-dev-images-dev-only-refresh/SKILL.md`, `/Users/briannasinger/.codex/memories/skills/fwm-codex-chat-transcript-upload/SKILL.md`, and `/Users/briannasinger/.codex/memories/skills/fwm-image-review-dashboard-workflow/SKILL.md`.
[2026-06-18] - Amazon taxonomy browser fallback after bad image-table labels: `temp_resumechat.rtf`, `amazon-browser-fallback`, clothing types in the image table are wrong, title, breadcrumb, 304 unique Amazon rows.
[2026-06-18] - Search memory first when a dev-only taxonomy thread crashed, image-table clothing labels are suspect, or browser-derived evidence should feed the existing audit/verify/promote loop.
[2026-06-18] - Learning: Stop using `clothing_type_id` once you reject it; lean browser title/breadcrumb collection beat screenshot-heavy fallback and fit the existing dev taxonomy pipeline.
[2026-06-18] - Transcript archival for recovered/current FWM chats: `scripts/upload-codex-chat-transcript.mjs`, `/private/tmp`, `chat_key`, `FWM_Data/_archive/transcripts`, readback.
[2026-06-18] - Search transcript archival memory first for `update the transcripts table` or crashed-chat recovery where you expect the conversation archived and continued.
[2026-06-18] - Learning: Rebuild compact JSON outside the repo, upload with the standard script, and verify by `chat_key` using actual table columns only.
[2026-06-17] - Dev-only taxonomy dashboard throughput and saved-approval applies: `taxonomy-review-dashboard`, `dev-images:taxonomy-audit`, `dev-taxonomy-review-decisions`, auto-advance, shard-count, `needs_manual_review`.
[2026-06-17] - Search taxonomy dashboard memory first for speeding up the dev taxonomy dashboard, parallelizing dry-run collection, or applying already-saved review decisions to the dev DB.
[2026-06-17] - Learning: Report-scoped saved decisions need server-side exclusion too; deterministic shards plus millisecond stems prevent parallel packet collisions.
[2026-06-17] - Dev-only refresh guardrails and dry-run promotions: `docs/dev-images-table-refresh-plan.md`, `supabase/dev-migrations`, `dev-supabase-guard.mjs`, `gosqgqpftqlawvnyelkt`.
[2026-06-17] - Search dev-only refresh memory first for FWM dev-only refresh implementation that must avoid production migrations and proceed through guarded dry-runs and verifier reruns.
[2026-06-17] - Learning: Read the plan first, keep `supabase/migrations` untouched, and rerun baseline/preview/state verifies after each approved promotion.
[2026-06-16] - AWIN queue and affiliate-link pipeline: `awin_scrape_work_queue.csv`, `scrape_awin_affiliate_queue.py`, `affiliate_monetization_gate_runbook.md`, `generate_awin_affiliate_links.py`, 60678 eligible rows.
[2026-06-16] - Search AWIN memory first for AWIN/non-Amazon pipeline work, especially when the task starts from applied-advertiser queues or needs AWIN-link generation from image/review data.
[2026-06-16] - Learning: Split queue work into bounded batches if one merchant hangs; plan in markdown first and reuse `FWM_Data/00_raw_scraped_data` plus affiliate-lead reports.
[2026-06-16] - Cleanup audit and delete-ready staging: `aug_epoch_7.pt`, `git clean -ndX`, `READY_TO_DELETE_old_review_bundles_20260616`, `measurement_row_inventory.csv`.
[2026-06-16] - Search cleanup memory first for evidence-based FWM cleanup tasks, Finder-openable delete targets, or questions about whether large generated artifacts are still worth keeping.
[2026-06-16] - Learning: Use `git clean -ndX` only as an audit surface, quarantine old review bundles into one holding folder, and prefer the approved-only measurement inventory over oversized broad row dumps.
[older] - Image-review dashboard local instances and subset packaging: `image-review-dashboard`, `human_labeled_returns`, `localhost:4173`, `SUBJECT_TOO_SMALL`, `FWM_IMAGE_REVIEW_INCLUDE_IMAGE_ONLY=1`.
[older] - Use image-review dashboard memory for desktop dashboard planning/debugging, immutable workbook flows, subset package creation, startup bucket mismatches, and main review-backlog counting; applies to cwd `/Users/briannasinger/Projects/FWM/FWM_Repo`.
[older] - Mobile image-review v039 baseline and persistence: `v039_COPY_TO_PHONE_10000cards_20260615T144500Z`, `fwmprogress=`, `currentReviewFileLabel()`, `human_labeled_returns`, `overlapCount: 0`.
[older] - Use mobile image-review memory for phone-batch generation, exclusion against current human decisions, import/export recovery, and future batch naming/baseline rules in cwd `/Users/briannasinger/Projects/FWM/FWM_Repo`.
[older] - Data-pipeline cleanup and lifecycle layout: `FWM_Data`, `cleanup/data-pipeline-layout-2026-06-15`, `3caa481`, Stage 04 count, generated data should generally not live in Git.
[older] - Use data-pipeline cleanup memory for lifecycle-based layout questions, repo/data-root cleanup planning, merge/branch cleanup, Stage 01 explanation, and Stage 04 approved-count logic; applies to cwd `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`.
[older] - Weight-estimation CV experiment: `experiments/weight_estimation_cv`, CLIP, 24.8 lbs MAE, 26.1 lbs 211+ MAE, catalog measurement search, `P@50 = 0.7619`.
[older] - Use weight-estimation memory for research-first CV experiment context where inferred weight should stay isolated and be evaluated as a soft ranking boost for measurement search, not as a direct display/hard filter.
[older] - Resume PDF handoff defaults: one-page PDF, restrained formatting, text-extractable, professional resume.
[older] - Use resume-generation defaults for future resume-generation requests; derived from extension notes rather than rollout summaries, so treat it as preference guidance and confirm only if the current request conflicts.
[2026-06-16] - FWM dev-only images refresh / taxonomy dashboard / browser fallback scope: Dev-only FWM refresh and taxonomy work that must stay off production, start from plans and dry-runs, scale review throughput, and fall back to browser-derived Amazon evidence when image-table labels are wrong.
[2026-06-16] - Applies to `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`; safe for future dev-only refresh work in this checkout family, but revalidate the approved dev ref, current report filenames, and current browser artifacts per run.
[2026-06-16] - Task: Implement dev-only refresh scaffolding and dry-run-first promotions, success.
[2026-06-16] - Rollout summary file: `rollout_summaries/2026-06-16T17-29-40-JiQf-fwm_dev_images_refresh_and_transcript_archive.md` with thread id `019ed17b-5041-7890-bb22-8f148f52baa7`.
[2026-06-16] - Keywords: `docs/dev-images-table-refresh-plan.md`, `supabase/dev-migrations`, `scripts/lib/dev-supabase-guard.mjs`, `scripts/dev-supabase-migrations.mjs`, `dev-images:status-audit`, `dev-images:browser-status-audit`, `dev-images:status:promote`, `dev-images:browser-status:promote`, `gosqgqpftqlawvnyelkt`.
[2026-06-17] - Task: Speed up taxonomy dashboard review, run parallel shards, and apply saved approvals to dev, success.
[2026-06-17] - Rollout summary file: `rollout_summaries/2026-06-17T18-01-26-ICe1-fwm_dev_taxonomy_dashboard_subagents_auto_advance.md` with thread id `019ed6be-c486-7fa1-ada6-177c528ade6d`.
[2026-06-17] - Keywords: `taxonomy-review-dashboard`, `dev-images:taxonomy-audit`, `dev-images:taxonomy:promote`, `dev-taxonomy-review-decisions`, report-scoped localStorage, auto-advance, shard-count, shard-index, `needs_manual_review`, `category_checked_at`, `staging.product_pages`.
[2026-06-17] - Task: Recover a crashed taxonomy thread and use browser fallback after bad image-table labels, success.
[2026-06-18] - Rollout summary file: `rollout_summaries/2026-06-17T21-16-35-AhTJ-fwm_amazon_taxonomy_browser_fallback_and_transcript_recovery.md` with thread id `019ed771-6e4c-7ec2-a044-e1be22dd4213`.
[2026-06-18] - Keywords: `temp_resumechat.rtf`, `amazon-browser-fallback`, clothing types in the image table are wrong, title, breadcrumb, `dev-images:taxonomy-audit`, `verify-dev-refresh-report.mjs`, `promote-dev-taxonomy-results.mjs`, 304 unique Amazon rows, 2270 planned taxonomy updates.
[2026-06-18] - When you said `This is dev-only: do not touch production Supabase, do not deploy the live website, and do not apply production migrations.` -> start with hard production-safety boundaries, not after-the-fact guardrails.
[2026-06-16] - When you said `Please read the plan first` and later `Do not run write-mode database operations until the guard and dry-run checks are in place.` -> read the plan, add guardrails, run dry-runs, summarize what would change, and pause before the first write.
[2026-06-17] - When you said `Can you make this faster with sub-agents?` and later `you should be continually using sub-agents` -> bounded parallel read-only collection is welcome when it increases throughput without bypassing approval gates.
[2026-06-17] - When you said `Anything that was already approved by hitting the Save Review of Decisions button in the dashboard, you can go ahead and add to the super base table in the dev database.` -> treat saved taxonomy approval JSON as standing permission to apply those dashboard-approved packets to dev.
[2026-06-18] - When you said `The clothing types in the image table are wrong` -> stop using `clothing_type_id` / `observed_clothing_type_ids` as taxonomy evidence and switch to page-derived evidence.
[2026-06-18] - When you said `I want you to collect as much taxonomy data as you can. When I come back, I’ll approve it in the dashboard.` -> bias toward report-only collection and dashboard-review packaging when approvals will happen later.
[2026-06-17] - When you asked for `one-click` / minimal pausing behavior -> keep permission asks short, explicit, and tied to the next concrete action.
[2026-06-16] - The surviving dev-only loop is: read `docs/dev-images-table-refresh-plan.md`, keep schema work in `supabase/dev-migrations/`, run the appropriate dry-run audit, inspect the `FWM_Data/_reports/` artifact, apply only the approved promotion, then rerun baseline verify, preview contract verify, and state verify.
[2026-06-17] - The approved dev Supabase target across these runs was ref `gosqgqpftqlawvnyelkt`, and `git diff --name-only -- supabase/migrations` staying empty was an explicit safety check after write-mode work.
[2026-06-17] - The taxonomy dashboard is driven by promotion dry-runs plus saved decision JSON under `FWM_Data/_reports/taxonomy-review-decisions/`; report-scoped localStorage alone is not enough, so the server also needs to exclude already-decided `product_page_id`s and auto-advance to the newest pending packet.
[2026-06-17] - Deterministic parallel collection used `--shard-count/--shard-index`, repeated `--exclude-approval-report`, repeated `--exclude-taxonomy-report`, millisecond-stamped filenames, and conservative audit settings like `--limit=100-200`, `--max-per-domain=1`, `--per-domain-delay-ms=750`, `--timeout-ms=8000`.
[2026-06-17] - Saved dashboard approval files are the reusable approval artifact for dev taxonomy applies; the promotion path should also clear `needs_manual_review = false` and write manual-review metadata into `raw_metadata`.
[2026-06-18] - For Amazon taxonomy in this repo, browser-derived title plus breadcrumb was the practical fallback once you rejected image-table clothing hints; it fit the existing audit/verify/promote loop better than forcing a new API integration with higher credential/setup friction.
[2026-06-17] - Relevant dev inspection surfaces were `https://supabase.com/dashboard/project/gosqgqpftqlawvnyelkt/editor?schema=staging`, `staging.product_pages`, `staging.product_page_clothing_type_tags`, and `staging.product_page_attribute_tags`.
[2026-06-16] - Failure: browser or dashboard verification fails with `bootstrap_check_in ... Permission denied (1100)`. Cause: Chromium/Playwright sandbox restriction on this Mac. Fix: rerun unsandboxed instead of retrying inside the sandbox.
[2026-06-16] - Failure: quick verification fails with `ERR_AMBIGUOUS_MODULE_SYNTAX`. Cause: mixed `require` with top-level `await`. Fix: use an async IIFE or pure ESM.
[2026-06-17] - Failure: already-saved taxonomy cards reappear after refresh. Cause: only client state was scoped; the server still returned those rows. Fix: treat saved decision files as source-of-truth for exclusion and auto-advance once a packet is exhausted.
[2026-06-17] - Failure: parallel taxonomy jobs collide on output names. Cause: second-level timestamp stems are too coarse. Fix: use millisecond-precision stems and deterministic shard/exclusion inputs.
[2026-06-18] - Failure: browser-derived taxonomy collection looks stalled. Cause: screenshot-heavy collection is too slow. Fix: switch to lean title/breadcrumb extraction and reserve screenshots for ambiguous cases.
[2026-06-18] - FWM transcript archiving / Supabase handoff scope: Updating `codex_chat_transcripts` for active, recovered, or handoff-heavy FWM chats with the repo’s uploader, compact JSON artifacts, and optional readback/local archive verification.
[2026-06-18] - Applies to `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`; safe for future FWM transcript archival in this project family, but confirm the exact source conversation, target table, and final `chat_key` per run.
[2026-06-18] - Task: Update the transcripts table with the repo’s existing uploader, success.
[2026-06-18] - Rollout summary file: `rollout_summaries/2026-06-17T21-16-35-AhTJ-fwm_amazon_taxonomy_browser_fallback_and_transcript_recovery.md` with thread id `019ed771-6e4c-7ec2-a044-e1be22dd4213`.
[2026-06-16] - Rollout summary file: `rollout_summaries/2026-06-16T19-03-53-rjXJ-fwm_cleanup_safe_delete_review_bundle_staging_and_transcript.md` with thread id `019ed1d1-93be-7101-bc7e-03e4839e3d3b`.
[2026-06-10] - Rollout summary file: `rollout_summaries/2026-06-04T19-08-13-w3q5-fwm_transcript_table_update.md` with thread id `019e9409-3cbd-7370-bb27-9677f54cf3bd`.
[2026-06-18] - Keywords: `scripts/upload-codex-chat-transcript.mjs`, `sync:codex-chat`, `sync:applypilot-chat`, `codex_chat_transcripts`, `/private/tmp`, `--skip-openai-summary`, `chat_key`, readback, `FWM_Data/_archive/transcripts`, `summary_model`.
[2026-06-17] - Task: Treat transcript archival as part of dashboard, experiment, cleanup, and crashed-thread handoff, success.
[2026-06-17] - Rollout summary file: `rollout_summaries/2026-06-16T17-29-40-JiQf-fwm_dev_images_refresh_and_transcript_archive.md` with thread id `019ed17b-5041-7890-bb22-8f148f52baa7`.
[2026-06-16] - Rollout summary file: `rollout_summaries/2026-06-16T17-13-17-0PXL-fwm_awin_affiliate_link_generation_and_transcript_upload.md` with thread id `019ed16c-529a-7892-88c9-6f2cc2a7b215`.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-11T12-11-39-2z4s-fwm_mobile_image_review_v039_persistence_s3_transcript_hando.md` with thread id `019eb698-5e3b-7c80-b57e-94f2d6efc3d0`.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-09T17-21-06-SDJZ-fwm_weight_estimation_cv_experiment_and_handoff.md` with thread id `019ead66-f427-7793-8a31-ab0c457949ef`.
[2026-06-09] - Rollout summary file: `rollout_summaries/2026-06-03T01-19-20-Z97B-fwm_image_review_dashboard_handoff_activation_and_transcript.md` with thread id `019e8b10-46da-7bb2-8c9f-314f5b95ac83`.
[2026-06-17] - Keywords: update the transcripts table, this chat, `temp_resumechat.rtf`, session JSONL, focused transcript JSON, message_count, summary_error, `codex-fwm`, durable archive copy.
[2026-06-18] - When you say `update the transcripts table` or `update the transcripts table with this chat` -> use the repo’s existing uploader flow instead of ad hoc DB writes or broad repo exploration.
[2026-06-18] - When the worktree is dirty or noisy -> keep transient transcript JSON outside the repo, usually in `/private/tmp`.
[2026-06-18] - When a crashed or resumed FWM chat is being continued -> treat transcript archival as part of done, not optional cleanup.
[2026-06-18] - When you ask for S3/transcript updates after main work -> treat transcript archival as part of normal wrap-up alongside the other handoff steps.
[2026-06-18] - The standard path is `scripts/upload-codex-chat-transcript.mjs`; `package.json` can expose both `sync:codex-chat` and `sync:applypilot-chat`, so confirm the correct table before uploading when repo context is ambiguous.
[2026-06-18] - The uploader expects a compact JSON transcript object, not a raw `.jsonl` stream; when no ready-made artifact exists, rebuild a focused JSON from the session log or recovered conversation text first.
[2026-06-18] - The stable deterministic upload shape in this repo family is `node scripts/upload-codex-chat-transcript.mjs <transcript.json> codex --skip-openai-summary` or `--table=codex_chat_transcripts` when needed.
[2026-06-18] - Useful success/readback fields are `ok`, `table`, `chat_key`, `message_count`, transcript timing, and any `summary_error`; the strongest quick verification is a readback by `chat_key`.
[2026-06-18] - When the transcript matters enough to preserve locally, mirror the compact JSON into `FWM_Data/_archive/transcripts/` after the upload.
[2026-06-18] - Failure: transcript update turns into noisy repo spelunking. Cause: broad search before checking the known uploader. Fix: jump straight to `scripts/upload-codex-chat-transcript.mjs`, `package.json`, and the intended session source.
[2026-06-18] - Failure: upload or verification uses the wrong conversation. Cause: multiple nearby JSONLs or recovered transcripts make `this chat` ambiguous. Fix: confirm the exact source file/session first.
[2026-06-18] - Failure: readback query fails with a 400 or syntax error. Cause: queried a non-column like `summary_model` or mixed `require` with top-level `await`. Fix: query actual table columns only and use an async IIFE or pure ESM.
[2026-06-18] - Failure: transcript upload creates unnecessary worktree churn. Cause: the JSON artifact was written into the repo. Fix: keep the upload artifact in `/private/tmp` and archive locally only if that extra copy is useful.
[older] - FWM image-review dashboard local instances and subset packaging scope: Planning, implementing, running, and debugging local FWM image-review dashboard instances, including immutable workbook flows, filtered subset packages, and startup state mismatches on desktop review dashboards.
[older] - Applies to `/Users/briannasinger/Projects/FWM/FWM_Repo` and `/Users/briannasinger/Projects/FWM`; safe for future FWM image-review dashboard work in this checkout family, but revalidate package paths, local ports, and current subset folders per run.
[2026-06-09] - Task: Plan and implement the local image-review dashboard with immutable workbooks, success.
[2026-06-09] - Rollout summary file: `rollout_summaries/2026-06-03T01-19-20-Z97B-fwm_image_review_dashboard_handoff_activation_and_transcript.md` with thread id `019e8b10-46da-7bb2-8c9f-314f5b95ac83`.
[2026-06-09] - Keywords: `image-review-dashboard`, `docs/image-review-dashboard-plan.md`, `human_labeled_returns`, `localhost:4173`, immutable workbooks, `review_notes`, crop metadata, approve reject neutral, `/api/parts`, `cd71507`.
[2026-06-15] - Task: Build focused `SUBJECT_TOO_SMALL` review subsets and fix custom-package startup bugs, success.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-15T14-55-26-f75Y-fwm_cv_review_subset_and_transcript_s3_handoff.md` with thread id `019ecbc7-c2f7-78e3-9a1f-19076f300ef6`.
[2026-06-16] - Rollout summary file: `rollout_summaries/2026-06-10T20-08-39-TEMW-fwm_awin_affiliate_dashboard_transcript_upload.md` with thread id `019eb326-b768-71c1-baec-76a78b110992`.
[2026-06-16] - Keywords: `SUBJECT_TOO_SMALL`, `figure_2_small_rejected_20260615`, `disapprove_subject_too_small_20260616`, `FWM_IMAGE_REVIEW_PACKAGE_DIR`, `FWM_IMAGE_REVIEW_RETURNS_DIR`, `FWM_IMAGE_REVIEW_INCLUDE_IMAGE_ONLY=1`, `firstAvailableBucket`, `ensureActiveBucketAndPart`, `localhost:4175`.
[2026-06-16] - Task: Count the main Supabase-qualified review backlog correctly, success.
[2026-06-16] - Keywords: `human_labeled_returns_manifest.json`, `image_review_eligible_index.json`, 286639 qualified rows, 242792 still needing human sorting, approve_candidates, needs_human_review, disapprove_candidates, unique image estimate.
[2026-06-09] - When you say `the original workbook should not be edited` -> keep source workbooks immutable and write reviewed outputs as new files in `human_labeled_returns` or a subset-specific returns folder.
[2026-06-09] - When you ask for reason filters, a visible reason toggle, a legend, and comments -> default to reason-based filtering plus universal `approve` / `reject` / `neutral` state with free-form `review_notes`, not tab-locked semantics.
[2026-06-09] - When you want a dashboard active locally, not just planned -> start the app and give the working URL instead of stopping at documentation.
[2026-06-15] - When you ask for a narrow set like `the disapprove candidates with the cv reason subject too small` -> build a dedicated filtered dashboard package rather than pointing you at the full review universe.
[2026-06-16] - When you say `the approve button won't click` -> debug the actual mounted package and local instance, not the abstract click handler.
[2026-06-16] - When you ask how many images still need sorting and then clarify `all images in the pipeline that are supabase qualfied` -> answer with the main eligible-index grounded queue, not a subset count.
[2026-06-09] - The source tree for desktop review work started as `outputs/02_supabase_needs_human_review_cv_first_pass/partial_170000_rows_cv_gated`, and reviewed outputs belong in `outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns` unless the run is a dedicated subset instance.
[2026-06-09] - `npm run image-review` starts the dashboard, and `curl -sSf http://localhost:4173/api/parts >/dev/null` is the fast liveness check before debugging any Save failure.
[2026-06-09] - The desktop dashboard supports universal decision changes across tabs/workbooks, free-form comments, undo, hide-saved/hide-duplicates, box select, and crop metadata export fields such as `crop_has_adjustment`, `crop_zoom`, and `crop_rotation_deg`.
[2026-06-15] - Custom subset instances are easiest to run by pointing the server at alternate `FWM_IMAGE_REVIEW_PACKAGE_DIR` and `FWM_IMAGE_REVIEW_RETURNS_DIR`; when the subset includes image-only rows, also set `FWM_IMAGE_REVIEW_INCLUDE_IMAGE_ONLY=1`.
[2026-06-16] - The canonical loose user phrase `figure-2 small` mapped to the actual CV reason code `SUBJECT_TOO_SMALL`, and the larger package math in the 2026-06-16 run was 6,465 total matches, 398 already saved/skipped, and 5,170 unsorted rows across 6 workbooks.
[2026-06-16] - For pipeline-wide queue counts, the row-level eligible index plus human-labeled manifest is the authoritative surface; unique-image estimates are only secondary sanity checks.
[2026-06-09] - Failure: Save fails with `Failed to fetch`. Cause: nothing is listening on `localhost:4173` or the active port. Fix: verify `/api/parts` first before assuming an API bug.
[2026-06-15] - Failure: custom subset dashboard looks empty or approve buttons appear dead. Cause: persisted state points at a nonexistent bucket/part in the mounted package. Fix: auto-select the first available bucket and part with rows, and confirm the package truly contains the intended bucket.
[2026-06-16] - Failure: subset row count looks lower than expected. Cause: default eligibility excludes image-only rows. Fix: use `FWM_IMAGE_REVIEW_INCLUDE_IMAGE_ONLY=1` for those focused instances.
[2026-06-16] - Failure: you ask for a loose reason phrase and filtering misses the intended rows. Cause: literal string matching ignored the canonical reason code. Fix: search manifests/README data for the formal CV code or summary first.
[2026-06-16] - Failure: unique-image backlog counts drift upward. Cause: counted workbook rows without tying them back to the eligible index. Fix: anchor counts to the eligible index and use unique-image numbers only as an explicitly secondary estimate.
[older] - FWM mobile image-review dashboard batches and persistence scope: Building and maintaining FWM phone-review batches, especially v039-based mobile HTML outputs, exclusion against current human decisions, persistence recovery, and mobile-specific export/import conventions.
[older] - Applies to `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`; safe for future mobile review batch/debugging in this checkout family, but always recheck the current `human_labeled_returns` folder and use a fresh versioned output path.
[2026-06-15] - Task: Build clean mobile batches and harden persistence/export behavior, success.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-11T12-11-39-2z4s-fwm_mobile_image_review_v039_persistence_s3_transcript_hando.md` with thread id `019eb698-5e3b-7c80-b57e-94f2d6efc3d0`.
[2026-06-15] - Keywords: `v039`, `build-mobile-bundle.mjs`, `mobile/app.js`, `human_labeled_returns`, `fwm_mobile_review_decisions_*.json`, `human_labeled_delta_*.json`, `currentReviewFileLabel()`, `fwmprogress=`, `importProgressFiles`, `remoteFallbackCount`.
[2026-06-15] - Task: Preserve the accepted v039 baseline and future handoff conventions, success.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-15T14-03-27-7GaP-fwm_mobile_review_v039_baseline_and_hygiene.md` with thread id `019ecb98-2a0c-7791-934c-ae47e5fb565f`.
[2026-06-15] - Keywords: `v039_COPY_TO_PHONE_10000cards_20260615T144500Z`, reviewedFilesScanned: 102, reviewedDecisionCount: 1125284, overlapCount: 0, do not use v032, new unique version, `codex_chat_transcripts`, `/private/tmp`.
[2026-06-15] - When you say `Make sure they don't have any images that I've already sorted before` and `Don't assume images that were in the last batch are sorted unless you see them in the human folder` -> exclude only rows present in the current human decision files/folder, not merely rows from prior issued batches.
[2026-06-15] - When you say reopening the HTML loses decisions or that export/reject-all breaks after a couple of tries -> prioritize durable recovery paths and robust repeated-tap behavior instead of assuming browser-local state will survive.
[2026-06-15] - When you say exported files are `numerous` and `all look the same` -> include the current HTML/batch label in export filenames.
[2026-06-15] - When you say `The latest successful phone batch is v039` and `Do not keep using v032` -> treat v039 as the accepted baseline and use a fresh versioned output folder for future batches.
[2026-06-15] - When you say `Do not push git unless I explicitly ask` -> S3/transcript work does not imply permission to push code.
[2026-06-15] - The generator had to follow the moved source tree under `outputs/02_supabase_needs_human_review_cv_first_pass/Archive/partial_170000_rows_cv_gated` or accept a `FWM_IMAGE_REVIEW_PACKAGE_DIR` override.
[2026-06-15] - The reliable exclusion scan reads `human_labeled_returns` decision JSONs such as `fwm_mobile_review_decisions_*.json` and `human_labeled_delta_*.json`, and excludes by decision key, row key, and source file/row number.
[2026-06-15] - The effective mobile recovery stack became immediate save (`localSaveBatchSize = 1`), URL-hash backup via `fwmprogress=`, file-backed Import, and export filenames based on `currentReviewFileLabel()`.
[2026-06-15] - Multi-file Import matters because copied/opened HTML files can behave like separate browser origins on the phone; imported JSON is the reliable fallback when local state is lost.
[2026-06-15] - Remote-image packs are much smaller than embedded-image packs and avoided the disk-space bottleneck during 10k-card iteration.
[2026-06-15] - Accepted baseline folder: `outputs/02_supabase_needs_human_review_cv_first_pass/v039_COPY_TO_PHONE_10000cards_20260615T144500Z`, with recorded verification `bundleRows: 10000`, `reviewedFilesScanned: 102`, `reviewedDecisionCount: 1125284`, `overlapCount: 0`.
[2026-06-15] - Failure: reopened phone HTML shows all cards unsorted again. Cause: Android/local HTML may reopen under a fresh origin or lose browser-local state. Fix: assume file-backed export/import is the durable recovery path, not localStorage alone.
[2026-06-15] - Failure: export or reject-all stops working after repeated taps. Cause: stale state and weak guarding around repeated actions. Fix: harden repeated-tap paths and keep saves/export lean.
[2026-06-15] - Failure: local 10k build stalls or is too small. Cause: offline embedded images and storage pressure. Fix: allow remote fallbacks for the 10k target and prefer remote-image packs when disk is tight.
[2026-06-15] - Failure: future batch accidentally overlaps already-sorted cards. Cause: reused stale human-folder assumptions or old version prefixes. Fix: rescan `human_labeled_returns` immediately before building and create a new versioned output folder instead of reusing old prefixes.
[older] - FWM data pipeline cleanup / lifecycle layout scope: Planning and executing the FWM move from legacy `outputs/`/Amazon-vs-non-Amazon organization to lifecycle-based `FWM_Data`, including repo hygiene, branch/merge flow, and stage-level explanation/counting after migration.
[older] - Applies to `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`; safe for future cleanup or layout-explanation work in this checkout family, but revalidate branch state, active untracked generated data, and current `FWM_Data` paths per run.
[2026-06-15] - Task: Inspect the repo and write the cleanup plan before edits, success.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-15T15-41-54-JwjN-fwm_data_pipeline_cleanup_merge_transcript_s3_and_stage4_cou.md` with thread id `019ecbf2-4c06-7e52-ab7d-93154f084873`.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-15T15-41-31-vD0j-fwm_data_pipeline_reorg_planning_only.md` with thread id `019ecbf1-f1e7-7dc2-9bea-d6a9d83aed07`.
[2026-06-15] - Keywords: `FWM_Data`, outputs, lifecycle stages, `backup/pre-cleanup-2026-06-15`, `origin/backup/pre-cleanup-2026-06-15`, generated data should generally not live in Git, transcripts in Supabase, Amazon vs non-Amazon metadata.
[2026-06-15] - Task: Implement cleanup, verify, merge, and preserve live claim-file edits, success.
[2026-06-15] - Keywords: `cleanup/data-pipeline-layout-2026-06-15`, `3caa481`, `6b91cd3`, `d9dbde0`, `_claims/*.claim`, `git switch main`, `git branch -D`, `FWM_Data/_archive`, `outputs/README.md`, `sync-data-to-s3.sh`.
[2026-06-15] - Task: Explain empty Stage 01 and count Stage 04 human-approved images, success.
[2026-06-15] - Keywords: `01_cleaned_normalized_data is empty`, migration_manifests, `2026-06-15-layout-migration.jsonl`, 30557 image rows, 28863 APPROVE, 12995 DISAPPROVE, `legacy_approved_batches`, `production_decision`.
[2026-06-15] - When you say `Before making any code or file changes, please inspect the current repository and write a detailed implementation plan` and `Do not edit files yet.` -> treat the task as plan-first / no-edit until the repo inventory and phase plan are explicit.
[2026-06-15] - When you ask for exact files/folders, phases, risks, and verification commands -> give phased cleanup plans with explicit validation rather than a loose narrative.
[2026-06-15] - When you say transcripts should live in Supabase and not clutter the repo root -> treat Supabase plus local archive/temp paths as the desired transcript architecture.
[2026-06-15] - When you say Amazon vs non-Amazon `should be metadata/columns, not top-level lifecycle folders` -> do not preserve source family as the main architecture in future reorganizations.
[2026-06-15] - When you say generated data should generally not live in Git and local archive should still exist -> keep Git focused on code/docs/schema and use `FWM_Data/_archive/` plus S3 for generated-history preservation.
[2026-06-15] - When another thread is actively writing `_claims/*.claim` files -> treat those claim files as live operational state and preserve them through branch cleanup.
[2026-06-15] - The target architecture here is lifecycle-based: raw scrape -> cleaned/normalized -> Supabase-qualified -> CV-annotated/pending review -> human-reviewed/ready to publish, with source/merchant distinctions living in metadata.
[2026-06-15] - `FWM_Data` is the sibling data root and the repo should remain code/docs/schema/migration focused; `.gitignore` may already block new transcript JSONs, but tracked transcript files still need explicit removal from Git.
[2026-06-15] - The safety point at the start of cleanup was `origin/backup/pre-cleanup-2026-06-15` at commit `27c5708`.
[2026-06-15] - The implemented cleanup centralized path helpers, updated dashboard defaults, added deprecation READMEs, moved generated data into `FWM_Data`, and adjusted S3 sync behavior.
[2026-06-15] - Merge state that mattered later: cleanup branch `cleanup/data-pipeline-layout-2026-06-15`, merge commit `3caa481` on `main`, and precommit suite passed unsandboxed with `20 passed`.
[2026-06-15] - Stage 01 remained empty because the cleanup was a layout/archive migration rather than a recomputation of normalized datasets; Stage 04 approved-count logic used latest-decision JSON plus legacy approved CSV rows, producing 30,557 approved image rows total.
[2026-06-15] - Failure: cleanup work starts drifting into ad hoc edits. Cause: skipped the requested inventory/plan phase. Fix: start with broad repo inspection, identify migration targets, and only then edit.
[2026-06-15] - Failure: branch cleanup gets blocked or confusing. Cause: unrelated claim-file edits or pulling the wrong branch. Fix: verify current branch before pulling, stash/preserve live claim edits, then switch/fast-forward/delete in that order.
[2026-06-15] - Failure: branch deletion refuses to proceed after merge. Cause: local branch is ahead of a stale remote-tracking ref. Fix: after confirming merge into `main`, `git branch -D` can be the correct local cleanup path.
[2026-06-15] - Failure: Stage counts look inflated. Cause: counted filenames or repeated exports instead of latest decisions / `production_decision`. Fix: count by decision content, not file naming.
[2026-06-16] - FWM AWIN affiliate queue and link generation scope: Finding the applied-advertiser queue, keeping AWIN scrape progress moving, adding the affiliate monetization gate, and generating AWIN affiliate-link artifacts from image/review data.
[2026-06-16] - Applies to `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`; safe for future AWIN/non-Amazon pipeline work in this checkout family, but revalidate current queue files, report locations, and live AWIN credentials or docs per run.
[2026-06-16] - Task: Locate the AWIN queue, keep scraping moving, and add the AWIN-vs-Sovrn monetization gate, success.
[2026-06-16] - Rollout summary file: `rollout_summaries/2026-06-10T20-08-39-TEMW-fwm_awin_affiliate_dashboard_transcript_upload.md` with thread id `019eb326-b768-71c1-baec-76a78b110992`.
[2026-06-16] - Keywords: `awin_scrape_work_queue.csv`, `scrape_awin_affiliate_queue.py`, `onewithswim.com`, `judge.me` batch, `affiliate_monetization_gate_runbook.md`, `select_affiliate_links.py`, `no_public_product_seed`, 1177 candidate rows, 142 unique product URLs.
[2026-06-16] - Task: Build the AWIN affiliate-link generation step from image/review data, success.
[2026-06-16] - Rollout summary file: `rollout_summaries/2026-06-16T17-13-17-0PXL-fwm_awin_affiliate_link_generation_and_transcript_upload.md` with thread id `019ed16c-529a-7892-88c9-6f2cc2a7b215`.
[2026-06-16] - Keywords: `awin_affiliate_link_generation_plan_2026-06-16.md`, `generate_awin_affiliate_links.py`, `pipeline_paths.py`, `FWM_Data/00_raw_scraped_data`, `FWM_Data/_reports/affiliate_links/awin`, `AWIN_PUBLISHER_ID`, `AWIN_ACCESS_TOKEN`, `baleaf.com`, 60678 eligible rows.
[2026-06-16] - When you say `find it and let me know when you're ready to start scraping them` -> locate the source queue first and confirm readiness before broader scrape work.
[2026-06-16] - When progress stalls and you say `Go ahead and keep going.` -> keep execution moving instead of over-explaining the blockage.
[2026-06-16] - When you ask for a step like `looks at the image data, gets product links that are associated with AWIN brands, and generates their affiliate link` and says `make a plan in markdown file before excecuting` -> plan in markdown first, then implement against the repo’s existing image/review and AWIN-report surfaces.
[2026-06-16] - The AWIN applied-advertiser queue lived at `outputs/measurement_coverage/20260609_human_labeled_approved_only/affiliate_network_leads/awin_scrape_work_queue.csv`, and `scrape_awin_affiliate_queue.py` reads that queue, writes `_claims`, and records run logs in the same output area.
[2026-06-16] - Provider-prioritized or bounded batches are the practical way to keep queue progress moving when one merchant hangs; in the observed run, a full queue got pinned and a smaller Judge.me batch recovered progress.
[2026-06-16] - `affiliate_monetization_gate_runbook.md` defined the selection rule: compare AWIN and Sovrn eligibility/payout signals, choose the better network, or leave the raw product URL if neither is linkable.
[2026-06-16] - `select_affiliate_links.py` is the central selector for AWIN-vs-Sovrn/no-link decisions, while actual URL generation stays network-specific.
[2026-06-16] - `generate_awin_affiliate_links.py` scans `FWM_Data/00_raw_scraped_data`, loads AWIN advertiser metadata from affiliate-lead reports, normalizes/dedupes product URLs, matches domains to `advertiserId`, and writes candidate/link-map artifacts under `FWM_Data/_reports/affiliate_links/awin/<run_id>/`.
[2026-06-16] - `pipeline_paths.py` is the right way to honor `FWM_DATA_DIR`, and a dry-run on a known populated domain like `baleaf.com` is a good smoke check before broader runs or live Link Builder calls.
[2026-06-16] - Failure: full AWIN queue appears stuck. Cause: one merchant can pin the whole run. Fix: split by provider/batch sooner and resume from a bounded slice.
[2026-06-16] - Failure: selector or link-generation smoke output is noisy and hard to inspect. Cause: domain filtering still scans unrelated CSVs or rereads heavy lookup data. Fix: tighten domain-scoped filtering and cache advertiser lookups once.
[2026-06-16] - Failure: monetization step is treated as complete after the selector runs. Cause: selector chooses the winning network but does not itself guarantee the downstream URL-generation integration is done. Fix: keep selection and network-specific generation as separate verified stages.
[2026-06-16] - FWM cleanup audit / delete-ready staging / measurement artifact hygiene scope: Evidence-based FWM cleanup work for large generated artifacts, archive/quarantine staging, and small targeted deletions where newer artifacts already supersede older ones.
[2026-06-16] - Applies to `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`; safe for future cleanup work in this checkout family, but revalidate current file existence, repo references, and whether you want quarantine versus direct deletion.
[2026-06-16] - Task: Audit safe-to-delete checkpoints and ignored caches, success.
[2026-06-16] - Rollout summary file: `rollout_summaries/2026-06-16T19-03-53-rjXJ-fwm_cleanup_safe_delete_review_bundle_staging_and_transcript.md` with thread id `019ed1d1-93be-7101-bc7e-03e4839e3d3b`.
[2026-06-16] - Keywords: `aug_epoch_7.pt`, `face_to_bmi_vit_summary_2026-06-09.md`, `git clean -ndX`, `.codex_vendor`, `.playwright-browsers`, `.venv-cv`, `experiments/weight_estimation_cv/cache`, Finder-openable paths.
[2026-06-16] - Task: Move old review bundles into a delete-ready holding folder, success.
[2026-06-16] - Keywords: `READY_TO_DELETE_old_review_bundles_20260616`, old_review_bundles, 34G, `v039_COPY_TO_PHONE_10000cards_20260615T144500Z`, quarantine move, Finder target.
[2026-06-15] - Task: Delete superseded measurement inventory artifacts instead of keeping giant row dumps, success.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-09T20-40-04-xnCd-fwm_delete_initial_measurement_inventory.md` with thread id `019eae1d-1d1c-76f2-856c-509f1ca86695`.
[2026-06-15] - Keywords: `measurement_row_inventory.csv`, `outputs/measurement_coverage/20260609_initial`, `outputs/measurement_coverage/20260609_human_labeled_approved_only`, approved-only snapshot, 77 MB, 9.5 MB, `c6d6cca`.
[2026-06-16] - When you ask whether a file is safe to delete -> give evidence-grounded deletion guidance, not speculation.
[2026-06-16] - When you ask for `the links to files I can delete safely so I can open them in finder` -> answer with path-forward, Finder-openable targets.
[2026-06-16] - When you say `put all the old review bundles that are safe to delete in their own folder` -> prefer a grouped, reversible quarantine step before irreversible deletion.
[2026-06-15] - When a newer approved-only artifact already covers the need -> you prefer removing large superseded generated artifacts instead of keeping them around.
[2026-06-16] - `aug_epoch_7.pt` was only referenced by docs/evaluator defaults and its own benchmark summary rejected it as a useful raw FWM signal, making it a strong archival-cleanup candidate rather than an active dependency.
[2026-06-16] - `git -C FWM_Repo clean -ndX` is useful for discovering ignored/generated cleanup candidates, but it also lists useful local config like `.env`, `config.dev.js`, and `index.dev.html`, so it should be used as an audit surface, not a blind deletion command.
[2026-06-16] - Strong cleanup candidates from the audit included `.codex_vendor/`, `.playwright-browsers/`, `.venv-cv/`, experiment caches, and other ignored/generated folders.
[2026-06-16] - The accepted reversible staging path for old review bundles was `FWM_Data/_archive/READY_TO_DELETE_old_review_bundles_20260616`, which consolidated the old tree into one ~34G Finder target.
[2026-06-15] - For measurement coverage, the approved-only inventory under `outputs/measurement_coverage/20260609_human_labeled_approved_only/measurement_row_inventory.csv` replaced the oversized broad-snapshot inventory while leaving summary/bin/chart artifacts intact.
[2026-06-16] - Failure: cleanup audit suggests deleting too much. Cause: reading `git clean -fdX` or similar as an action rather than an inventory. Fix: enumerate only the safe targets explicitly and call out useful local config that should stay.
[2026-06-16] - Failure: archived review-bundle triage becomes noisy and slow. Cause: the tree is huge. Fix: jump from size-based triage to a quarantine move when you want one delete-ready folder.
[2026-06-16] - Failure: deletion candidate list mentions folders that are already gone. Cause: the workspace changed during cleanup. Fix: verify a specific candidate still exists before naming it as a current deletion target.
[2026-06-15] - Failure: measurement coverage artifacts bloat unnecessarily. Cause: broad row-level inventories were kept after a narrower approved-only snapshot became the actual working artifact. Fix: keep the smaller approved-only inventory and delete only the superseded giant row dump.
[2026-06-15] - FWM weight-estimation CV experiment and handoff scope: Research-first FWM CV experiments around inferred user weight, with isolated experiment directories, product-shaped evaluation, and handoff/documentation rules for results that should inform search rather than direct user-facing display.
[2026-06-15] - Applies to `/Users/briannasinger/Projects/FWM` and `/Users/briannasinger/Projects/FWM/FWM_Repo`; safe for future work in this experiment family, but treat model metrics and artifacts as experiment-specific and revalidate before using them for product decisions.
[2026-06-15] - Task: Build and evaluate inferred-weight experiments in an isolated experiment directory, success.
[2026-06-15] - Rollout summary file: `rollout_summaries/2026-06-09T17-21-06-SDJZ-fwm_weight_estimation_cv_experiment_and_handoff.md` with thread id `019ead66-f427-7793-8a31-ab0c457949ef`.
[2026-06-15] - Keywords: `experiments/weight_estimation_cv`, CLIP, two-stage-model, 24.8 lbs MAE, 26.1 lbs 211+ MAE, catalog measurement search, `P@50 0.7619`, `http_403`, do not change any code yet.
[2026-06-15] - Task: Document findings, sync S3, and archive the transcript as part of handoff, success.
[2026-06-15] - Keywords: `weight_estimation_findings_2026-06-15.md`, `FWM_AWS_PROFILE=default scripts/sync-data-to-s3.sh`, `codex_chat_transcripts`, `/private/tmp/codex-weight-estimation-cv-transcript-2026-06-15.json`.
[2026-06-15] - When you say `Do not change any code yet` and ask for research first -> stay in research/planning mode until implementation is explicitly approved.
[2026-06-15] - When you say `store everything related to this experiment in its own directory. Don't mess with the outputs folder that I'm currently working on.` -> isolate experiments under their own directory and avoid touching active `outputs/` work.
[2026-06-15] - When you correct the product shape with `Users of my website don't submit images, they input measurements to search our database of images` -> evaluate against measurement-query product behavior, not image-query retrieval.
[2026-06-15] - When you ask to `document the findings, update S3 and the transcripts table` -> include durable findings docs plus the usual handoff surfaces instead of stopping at experiment code/results.
[2026-06-15] - The self-contained experiment area was `experiments/weight_estimation_cv/`, with scripts and reports kept there instead of in the active `outputs/` tree.
[2026-06-15] - The eval sample ended at 1,200 rows with 971 successful image downloads and 229 mostly-`http_403` failures.
[2026-06-15] - Pretrained torchvision encoders were less useful than the supervised CLIP-based work; the best global supervised point-estimate model was about `24.8 lbs MAE`, while a 211+ specialist regressor reached about `26.1 lbs MAE` for the high-weight segment.
[2026-06-15] - The durable product conclusion was not `show inferred weight directly` or `hard-filter by inferred weight`; inferred weight was more promising as a soft ranking boost layered on top of existing height/size search.
[2026-06-15] - Corrected measurement-search results preserved the distinctive handles: height/size-only `P@50 = 0.6484`; height/size + two-stage inferred-weight boost `P@50 = 0.7619`; height/size + global inferred-weight boost for 211+ items `P@50 = 0.3596` vs `0.2907` baseline.
[2026-06-15] - The handoff doc that captured the product-shaped conclusion was `experiments/weight_estimation_cv/reports/weight_estimation_findings_2026-06-15.md`.
[2026-06-15] - Failure: experiment findings sound promising but do not map to the real product. Cause: evaluation framed the held-out image as the query image. Fix: model measurement-input search over catalog images instead.
[2026-06-15] - Failure: high-weight performance remains poor even when overall MAE looks acceptable. Cause: naive global point estimates still underpredict the upper tail. Fix: treat the signal as ranking assistance, not a direct display/hard filter, and verify the tradeoff on the actual search task.
[2026-06-15] - Failure: S3 handoff looks stalled. Cause: the long-running sync lost its session handle. Fix: rerun the idempotent sync command and avoid touching unrelated dirty files while it completes.
[2026-06-18] - Supabase transcript table access: table is `public.codex_chat_transcripts`.
[2026-06-18] - Supabase transcript project/context docs say to use `docs/chatgpt_project_context/fwm_chatgpt_transcript_memory.md` only when needing to locate prior ChatGPT conversations by `chat_key`; prefer the higher-level context docs first unless a specific prior chat is needed.
[2026-06-18] - Supabase transcript uploader path: `/Users/briannasinger/Projects/FWM/FWM_Repo/scripts/upload-codex-chat-transcript.mjs`.
[2026-06-18] - Supabase transcript uploader default table: `codex_chat_transcripts`.
[2026-06-18] - Supabase transcript uploader endpoint shape: `${SUPABASE_URL}/rest/v1/${tableName}?on_conflict=chat_key`.
[2026-06-18] - Supabase transcript uploader requires env vars `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`; it reads repo-local `.env` if present.
[2026-06-18] - Supabase transcript uploader uses `apikey: SUPABASE_SERVICE_ROLE_KEY`, `Authorization: Bearer SUPABASE_SERVICE_ROLE_KEY`, `Content-Type: application/json`, and `Prefer: resolution=merge-duplicates,return=representation`.
[2026-06-18] - Supabase transcript upload command shape: `node scripts/upload-codex-chat-transcript.mjs <transcript.json> codex --skip-openai-summary` or `node scripts/upload-codex-chat-transcript.mjs <transcript.json> codex --table=codex_chat_transcripts --skip-openai-summary`.
[2026-06-18] - Supabase transcript JSON files should not live in the repo root; pass a transcript path or set `FWM_TRANSCRIPT_PATH`.
[2026-06-18] - Repo `.env.example` lists `SUPABASE_URL=https://gosqgqpftqlawvnyelkt.supabase.co`, `SUPABASE_SERVICE_ROLE_KEY=your-service-role-key`, `DEV_DATABASE_URL=postgresql://postgres.gosqgqpftqlawvnyelkt:your-password@aws-0-us-east-1.pooler.supabase.com:5432/postgres`, and `PROD_DATABASE_URL=postgresql://postgres.kmomndloorvrjzmiexxl:your-password@aws-0-us-east-1.pooler.supabase.com:5432/postgres`.
[2026-06-18] - Dev Supabase ref: `gosqgqpftqlawvnyelkt`.
[2026-06-18] - Dev Supabase URL: `https://gosqgqpftqlawvnyelkt.supabase.co`.
[2026-06-18] - Production Supabase ref in guard code: `kmomndloorvrjzmiexxl`.
[2026-06-18] - Production Supabase URL in guard code: `https://kmomndloorvrjzmiexxl.supabase.co`.
[2026-06-18] - Scripts abort when `SUPABASE_URL` is unset, points at production, or points outside the approved dev allowlist for dev-only work.
[2026-06-18] - S3 access: bucket URL is `s3://fwm-scraping-data-briannasinger`.
[2026-06-18] - S3 data path on Mac: `/Users/briannasinger/Projects/FWM/FWM_Data`.
[2026-06-18] - S3 repo path on Mac: `/Users/briannasinger/Projects/FWM/FWM_Repo`.
[2026-06-18] - S3 data path on Windows: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data`.
[2026-06-18] - S3 repo path on Windows: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Repo`.
[2026-06-18] - S3 AWS CLI profile: `fwm`.
[2026-06-18] - S3 AWS region: `us-east-1`.
[2026-06-18] - S3 IAM user identity recorded in docs: `arn:aws:iam::326804802943:user/codex-sync`.
[2026-06-18] - S3 docs say `codex-sync` has bucket-scoped access to `s3://fwm-scraping-data-briannasinger`.
[2026-06-18] - S3 docs say the `fwm` profile uses IAM access keys, not `aws login`.
[2026-06-18] - S3 docs say if the key is invalid or rotated, use an AWS admin/root session to create a new access key for IAM user `codex-sync`, then update local profile `fwm`.
[2026-06-18] - S3 credential verification command: `aws sts get-caller-identity --profile fwm`.
[2026-06-18] - S3 backup helper scripts: `scripts/sync-data-to-s3.ps1` and `scripts/sync-data-to-s3.sh`.
[2026-06-18] - S3 backup workflow defaults to the dedicated AWS profile `fwm`.
[2026-06-18] - S3 local config expected in `.env`: `FWM_DATA_DIR`, `FWM_S3_BUCKET=s3://fwm-scraping-data-briannasinger`, and `FWM_AWS_PROFILE=fwm`.
[2026-06-18] - S3 Mac `.env` should set `FWM_DATA_DIR=/Users/briannasinger/Projects/FWM/FWM_Data`.
[2026-06-18] - S3 Windows backup command: `.\scripts\sync-data-to-s3.ps1`.
[2026-06-18] - S3 restore command on Windows: `aws --profile fwm s3 sync s3://fwm-scraping-data-briannasinger C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data --exclude ".DS_Store"`.
[2026-06-18] - S3 restore handoff says AWS CLI on Windows may be installed at `C:\Program Files\Amazon\AWSCLIV2\aws.exe` and may not be on `PATH`; prefer calling the full executable path directly in a fresh shell.
[2026-06-18] - S3 PowerShell restore command from handoff: `& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' --profile fwm s3 sync 's3://fwm-scraping-data-briannasinger' 'C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data' --exclude '.DS_Store'`.
[2026-06-18] - S3 docs say `FWMDataBucketSyncPolicy` allows list/read/write/delete operations only for `s3://fwm-scraping-data-briannasinger`.
[2026-06-18] - S3 docs say previous broad `AmazonS3FullAccess` managed policy was detached from `codex-sync`.
[2026-06-18] - S3 is disaster/remote backup for the local lifecycle data tree; keep local archive folders under `FWM_Data/_archive/` before syncing.
[2026-06-18] - No stored family details were found in the memory summary or registry I inspected.
[2026-06-18] - No stored job title was found in the memory summary or registry I inspected.
[2026-06-18] - No stored personal interests outside the FWM project and resume/PDF preference were found in the memory summary or registry I inspected.
```

Confirmation: this is the complete set I found in the provided memory summary, the searchable memory registry, and the locally verified Supabase/S3 repo docs. I did not find additional stored personal/family/job details in those sources. Secret credential values are intentionally not included; the export names the env vars, profiles, scripts, bucket, project refs, and access workflows needed to use the data.
