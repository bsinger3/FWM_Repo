# FWM Mistakes, Bad Assumptions, And Wild Goose Chases

Generated: 2026-06-19

Audience: Claude Code or any future coding assistant working on Friends With Measurements.

Source: scanned `public.codex_chat_transcripts` in the FWM dev Supabase project. The scan covered 333 rows:

- `chatgpt_export`: 252
- `codex`: 75
- `chatgpt_project_context`: 4
- `fwm`: 1
- `fwm-nonamazon-petal-swimoutlet-scrape-update-redacted`: 1

This is not a blame file. It is a map of traps we have already fallen into, so the next assistant can move faster and avoid repeating them.

## Highest Priority Rules For Claude

1. Treat production safety as the first requirement, not a late check.
2. Do not use `clothing_type_id` or `observed_clothing_type_ids` as trustworthy taxonomy evidence unless the user explicitly revalidates them.
3. Do not treat browser/local/mobile state as durable. Export/import files and `human_labeled_returns` are the durable review surfaces.
4. Do not put bulky generated artifacts, phone bundles, transcript JSONs, or raw scrape outputs into Git.
5. For transcript work, use `scripts/upload-codex-chat-transcript.mjs`, write transient JSON to `/private/tmp`, and verify by `chat_key`.
6. For Playwright failures on this Mac, check for `bootstrap_check_in ... Permission denied (1100)` before debugging application code.
7. Before any scrape, check active claims, completed claims, existing outputs, S3, and the scrape triage plan.
8. When the user corrects an assumption, stop using the rejected evidence immediately.

## Report Table

| Area | Mistake or wild goose chase | What actually happened | Future rule |
| --- | --- | --- | --- |
| Dev vs production Supabase | Treating dev-only work as if production risk could be checked later | The dev image refresh work required explicit guards, dry runs, and keeping `supabase/migrations` untouched. The confirmed dev ref was `gosqgqpftqlawvnyelkt`; production ref was `kmomndloorvrjzmiexxl`. | Start every DB-changing FWM task by confirming dev/prod refs, reading the relevant plan, running dry-run output, and pausing before writes unless the user already gave standing permission. |
| Taxonomy evidence | Trusting image-table clothing labels | The user said: `The clothing types in the image table are wrong`. After that, `public.images.clothing_type_id` and `observed_clothing_type_ids` were no longer acceptable taxonomy evidence. Browser title and breadcrumb evidence became the better fallback. | Use page-derived evidence for taxonomy unless a current verified dataset proves otherwise. |
| Taxonomy audit dedupe | Passing exclude reports in the wrong form | A larger browser-taxonomy wave produced duplicates because the exclude argument was passed incorrectly. The correct form was `--exclude-taxonomy-report=/path`. | For audit CLIs, verify argument shape with a tiny dry run before launching a broader packet. |
| Taxonomy hallucination guard | URL-derived category guesses looked too confident | The taxonomy work needed hardening against URL-derived hallucinations. Some apparent categories were not safe without page evidence. | Treat URL slugs as weak hints. Require title/breadcrumb/page evidence before safe promotion. |
| Product category staging | Allowing invalid or low-quality categories and brand values | Product-category staging produced bad values like `other` categories, empty columns, `WWW` as a brand, and rows needing manual review. | Category suggestions must agree with accepted garment type; never use `other` as a clothing category; treat brand-from-domain heuristics cautiously. |
| Dev schema access | Assuming staging schema was available through PostgREST | Staging tables were not exposed through PostgREST, so direct REST assumptions failed and CLI/script paths were needed. | Check schema exposure before choosing REST vs Supabase CLI/Postgres queries. |
| Product framing for CV experiment | Evaluating inferred weight as image-query retrieval | The product does not ask users to submit images. Users enter measurements to search a catalog of images. Early framing as held-out image retrieval was wrong. | Model experiments around measurement-input search over catalog images. Do not optimize for an image-query product the site does not have. |
| Inferred weight usage | Treating inferred weight as displayable or hard-filterable | The best conclusion was that inferred weight was only promising as a soft ranking boost. High-weight examples remained difficult, and naive point estimates underpredicted the upper tail. | Never show inferred weight directly and never hard-filter by it without a fresh product decision. |
| Model/repo probing | Chasing unavailable external model weights | The `face-to-bmi-vit` repo had train/demo code but no usable releases, and one probe initially used the wrong GitHub org and got a 404. | Check releases/weights before cloning or integrating external CV repos. |
| Image-review dashboard server | Debugging Save as an app bug when the server was down | `Failed to fetch` often meant nothing was listening on `localhost:4173`. | First run `curl -sSf http://localhost:4173/api/parts >/dev/null` before debugging save/export behavior. |
| Image-review subset startup | Custom package looked empty and approve buttons would not click | The dashboard persisted `state.bucket=needs_human_review`, while the custom package only had `disapprove_candidates`. The app requested a nonexistent bucket. | When mounting a custom package, auto-select the first available bucket/part and reset invalid persisted state. |
| Image-review subset counts | Under-counting focused rows | Some focused packages required `FWM_IMAGE_REVIEW_INCLUDE_IMAGE_ONLY=1`; otherwise image-only rows were excluded. | If a subset includes image-only rows, set the env var and verify package row counts against the manifest. |
| Crop UI | Rotation-only crop behavior trimmed images | Rotation-only adjustments accidentally acted like crop/cover behavior and could shave off image edges. | Keep rotation-only rendering in contain mode; use focused assertions around crop transform behavior. |
| Mobile review persistence | Trusting browser local state on phone | Reopening copied HTML could show cards as unsorted again because Android/local HTML browser origin/localStorage behavior was not durable. | Treat file-backed export/import as the durable path. LocalStorage is only convenience. |
| Mobile localStorage quota | Export/reject/tap behavior broke under storage pressure | Phone localStorage quota caused autosave/export failures and repeated-tap instability. | Keep mobile saves lean, save immediately in small batches, and provide file import/export recovery. |
| Mobile batch versioning | Reusing old `v032` assumptions | The user asked for a unique folder/prefix and later established `v039_COPY_TO_PHONE_10000cards_20260615T144500Z` as the accepted baseline. | Never keep using stale phone-batch prefixes. Generate a fresh versioned output folder and label exports with the current HTML/batch label. |
| Already-sorted exclusions | Assuming prior issued batches were already sorted | The user corrected this: do not assume images in the last batch were sorted unless they appear in the human folder. | Re-scan current `human_labeled_returns` immediately before generating new batches. Exclude only actual saved decisions. |
| Pipeline counts | Counting filenames or repeated exports instead of latest decisions | Stage 04 counts could inflate if counting files rather than decision content. | Count by latest decision content and `production_decision`, not file names or exported workbook count. |
| Measurement coverage heuristic | Overvaluing generic/rejected rows | The first scoring pass for measurement coverage was too permissive, catching rejected/manual false positives and generic text. | Tune coverage heuristics against approved-only/human-labeled rows and inspect top candidates before trusting a ranking. |
| Data layout | Keeping Amazon vs non-Amazon as top-level lifecycle architecture | The user clarified that Amazon vs non-Amazon should be metadata/columns, not top-level lifecycle folders. | Keep lifecycle stages top-level: raw, cleaned, Supabase-qualified, CV annotated, human reviewed. Treat source family as metadata. |
| Git artifact hygiene | Trying to back up huge generated artifacts through Git | The repo had large generated output trees, model artifacts, and thousands of untracked files. GitHub was the wrong storage layer. | Git is for code, docs, schema, and small plans. Use `FWM_Data/_archive/` plus S3 for generated history. |
| Transcript artifacts | Letting transcript JSONs clutter the repo root | Transcript work repeatedly produced local JSON artifacts; the desired architecture became Supabase plus `/private/tmp` and optional local archive copies. | Never place transient transcript JSON in repo root. Upload to `codex_chat_transcripts` and archive under `FWM_Data/_archive/transcripts/` only when useful. |
| Transcript row selection | Uploading or preparing the wrong conversation | One transcript update initially opened a worker/subagent session rather than the main chat. | For `this chat`, match the current session by recent user wording and verify source before upload. |
| Transcript readback | Querying columns that were not actually present | Readback once failed because it used non-columns like `summary_model` or mixed CommonJS `require` with top-level `await`. | Query actual table columns only; use an async IIFE or pure ESM for Node one-offs. |
| Playwright on Mac | Treating Chromium launch failures as app regressions | Sandboxed Playwright repeatedly failed with `bootstrap_check_in ... Permission denied (1100)`. Unsandboxed reruns passed. | If all browser tests fail instantly with Mach port errors, rerun outside sandbox before touching app code. |
| Precommit and commits | Using `--no-verify` after sandbox failure without a clean external pass | Some commits were made after sandboxed hooks failed. Later runs showed unsandboxed hooks can pass cleanly. | Prefer rerunning the same precommit/test command outside sandbox and only commit after it passes. |
| Active scrape claims | Branch changes collided with `_claims/*.claim` files | Live claim edits from active scrape work blocked branch switching and could have been lost. | Treat `_claims/*.claim` as live operational state. Preserve or stash intentionally; do not casually revert or commit unrelated claims. |
| Branch cleanup | Pulling/switching while on the wrong branch | Local branch cleanup got confusing after pulling `origin/main` while still on a cleanup branch. | Verify current branch before pull/switch/delete. After confirmed merge, fast-forward `main`, then delete old local branch if safe. |
| AWS profile setup | Wrong prompt/credential file during AWS setup | Several rounds were needed because access key ID and secret were pasted into wrong prompts or malformed in the credentials file. | Use `aws configure --profile fwm` or the documented full AWS CLI path, then verify with `aws sts get-caller-identity --profile fwm`. |
| AWS profile drift | Assuming `fwm` profile exists everywhere | Some Mac runs lacked the `fwm` AWS profile and used `default`; later docs standardize `fwm`. | Check the current machine. Prefer `fwm` when available; if using `default`, state it explicitly in the handoff. |
| AWS permissions | Too-broad S3 permissions | The setup moved away from broad `AmazonS3FullAccess` to bucket-scoped access for `codex-sync`. | Use the dedicated `codex-sync` IAM user and bucket-scoped policy for `s3://fwm-scraping-data-briannasinger`; do not use root credentials for normal sync. |
| S3 sync sessions | Assuming a lost long-running sync was still progressing | One S3 handoff looked stalled after the session handle was lost. | Rerun idempotent sync commands when session state is uncertain; do not infer success from a lost handle. |
| Non-Amazon scrape targets | Re-probing blocked stores without new evidence | Multiple stores hit WAF, captcha, DataDome, PerimeterX, 403, 429, auth walls, or unavailable public endpoints. | If blocked by WAF/captcha/403/429, stop and mark blocked unless there is a new public endpoint, provider, or human-cleared browser plan. |
| Shopify/products scraping | Rate limits and partial checkpoints | MiracleSuit, SwimOutlet, and Andie hit HTTP 429s; SwimOutlet had products.json checkpoints that should not be restarted casually. | Reuse checkpoints, respect cooldowns, and schedule revisits rather than restarting catalog discovery from scratch. |
| Amazon direct scraping | Amazon auth/sign-in wall | Amazon direct review scraping hit sign-in/claim walls for ASIN smoke tests. | Treat Amazon direct scraping as blocked unless accessible ASINs or Apify/provider coverage is available. |
| AWIN queue execution | One merchant pinned a full queue run | A full AWIN queue could appear stuck because one merchant pinned the whole run. | Split by provider/domain/bounded batches earlier; use claims and logs to resume smaller slices. |
| AWIN monetization stage | Treating selector output as full URL generation | The selector chooses AWIN vs Sovrn/no-link, but actual network-specific URL generation must be separately verified. | Keep network selection and generated tracking-link output as separate stages with smoke tests. |
| AWIN credentials | Running live link generation before credentials are available | Link generation should dry-run first, and live Link Builder calls require `AWIN_PUBLISHER_ID` and `AWIN_ACCESS_TOKEN`. | Always support dry-run and domain-scoped smoke tests before credentialed live API calls. |
| Frontend vs database logic | Trying to change matching logic in frontend | Older guidance noted AND/OR matching logic belongs in Supabase SQL/RPC, not frontend display code. | Frontend should send inputs and render results; matching semantics live in database functions/RPC. |
| Supabase anon/config 401s | Assuming RLS/table policy before checking config | A 401 during activity tracking was likely wrong anon key or wrong project URL in `config.js`. | Before debugging RLS, inspect `window.SUPABASE_URL` and anon key prefix in the running frontend. |
| Schema changes | Forgetting frontend follows schema | Older URL/search automation notes emphasized updating frontend select statements, RPC calls, insert payloads, rendering, filters, and nullable assumptions after schema changes. | After schema migration/type generation, audit every frontend/API assumption that touches changed fields. |
| Data normalization | Treating LLM normalization as magic | Older ChatGPT guidance warned that handing raw CSVs to an LLM and saying "normalize this" creates subtle errors. | Use controlled transformation pipelines, reference files, one obvious input/output, and deterministic checks. |

## Representative Transcript Rows

These are the most useful rows to inspect if Claude needs more detail.

| Topic | Date | Title | Source | Chat key |
| --- | --- | --- | --- | --- |
| Current taxonomy and catalog-image prep | 2026-06-18 | FWM taxonomy category and catalog image prep current chat | codex | `codex-fwm-taxonomy-category-and-catalog-image--a4e93309f21ba146` |
| Dashboard/product-link cleanup and wrong transcript-source correction | 2026-06-18 | FWM taxonomy review dashboard and product-link status cleanup - 2026-06-18 | fwm | `fwm-fwm-taxonomy-review-dashboard-and-produc-5458897924b921d3` |
| Amazon taxonomy browser fallback and rejected clothing labels | 2026-06-17 | FWM Amazon taxonomy browser fallback and current chat transcript | codex | `codex-fwm-amazon-taxonomy-browser-fallback-and-fa54c0aa7547f645` |
| Dev image refresh guardrails | 2026-06-15 | FWM dev images table refresh planning and implementation handoff | codex | `codex-fwm-dev-images-table-refresh-planning-an-d7f768da9e080886` |
| Image review dashboard desktop bugs | 2026-06-09 | FWM image review dashboard fixes - 2026-06-09 | codex | `codex-fwm-image-review-dashboard-fixes-2026-06-f48d2c712844ba35` |
| Image review dashboard handoff and Save failure | 2026-06-09 | FWM image review dashboard handoff and activation - 2026-06-09 | codex | `codex-fwm-image-review-dashboard-handoff-and-a-6fbb0e8525aa6505` |
| Subject-too-small subset package | 2026-06-15 | FWM image review dashboard subset: subject too small CV rejects | codex | `codex-fwm-image-review-dashboard-subset-subjec-635326c3df11ff43` |
| Mobile v039 persistence | 2026-06-15 | FWM mobile image review v039 persistence and import handoff | codex | `codex-fwm-mobile-image-review-v039-persistence-49e76ead5e43757f` |
| Mobile v033 quota and split-bundle work | 2026-06-11 | FWM mobile image review v033 bundle handoff | codex | `codex-fwm-mobile-image-review-v033-bundle-hand-43cb44517f878b6d` |
| Data layout cleanup and branch/claim handling | 2026-06-15 | FWM data pipeline layout cleanup, merge, and Stage 04 approved image count | codex | `codex-fwm-data-pipeline-layout-cleanup-merge-a-37216f26e8a82430` |
| Repo cleanup and transcript artifact cleanup | 2026-06-15 | FWM repo cleanup planning and transcript upload 2026-06-15 | codex | `codex-fwm-repo-cleanup-planning-and-transcript-bebece8e11a3db40` |
| AWIN affiliate link generation | 2026-06-16 | FWM AWIN affiliate link generation script and credential handoff | codex | `codex-fwm-awin-affiliate-link-generation-scrip-ef5120bfd720d6d3` |
| AWIN dashboard/custom package issue | 2026-06-16 | FWM AWIN affiliate linking and image approval dashboard | codex | `codex-fwm-awin-affiliate-linking-and-image-app-b599743412135c1b` |
| Weight-estimation product framing | 2026-06-09 | FWM CV inferred weight experiment and catalog-search handoff | codex | `codex-fwm-cv-inferred-weight-experiment-and-ca-833967235aae95ca` |
| Measurement coverage heuristic tuning | 2026-06-09 | FWM measurement coverage and transcript table update - 2026-06-09 | codex | `codex-fwm-measurement-coverage-and-transcript--b6ed0dd0dbfa78db` |
| Cross-laptop repo/OneDrive issue | 2026-05-27 | Cross-laptop FWM repo alignment and Sovrn triage handoff | codex | `codex-cross-laptop-fwm-repo-alignment-and-sovr-59e04d12b983e822` |
| Product category staging quality issues | 2026-05-20 | FWM Product Category Staging And Manual Review | codex | `codex-fwm-product-category-staging-and-manual--9d1f0e07f768cf13` |
| Non-Amazon scrape rescue and rate limits | 2026-05-05 | Non-Amazon Scrape Rescue Thread - MiracleSuit to Bloomingdale's AQUA | codex | `codex-non-amazon-scrape-rescue-thread-miracles-2cf81bfd31e2a6b5` |
| Amazon auth wall | 2026-05-15 | Amazon Direct Review Scraper Setup | codex | `codex-amazon-direct-review-scraper-setup-bbf9551478b57d6c2` |
| Lulus / PerimeterX blocking | 2026-05-15 | Lulus Review Scrape Continuation and Fresh Scrape Attempt | codex | `codex-lulus-review-scrape-continuation-and-fre-625c3fe086e0d6c2` |
| Stacees endpoint nuance | 2026-05-17 | Stacees Non-Amazon Scrape - 2026-05-17 | codex | `codex-stacees-non-amazon-scrape-2026-05-17-9bee8fa988c51dea` |
| Older frontend/Supabase config 401 trap | 2026-02-24 | Tracking User Activity | chatgpt_export | `fwm-chatgpt-699dd8b3-25fc-832e-a830-b771b0df766c` |
| Older schema/frontend change warning | 2026-04-14 | URL-based Search Automation | chatgpt_export | `fwm-chatgpt-69dda00a-4d28-83ea-9d6e-9d68f7cd966f` |
| Older controlled CSV normalization guidance | 2026-03-16 | AI Data Normalization Plan | chatgpt_export | `fwm-chatgpt-69b85026-0db8-8325-9070-90725b7cb206` |

## How Claude Should Use This

Before making code changes, Claude should scan the relevant row(s) above and apply the matching rule. If the current task touches DB writes, image review, mobile bundles, scraping, S3, transcripts, taxonomy, or Git hygiene, assume one of these prior traps is nearby.

Recommended first commands or checks by task type:

- Dev Supabase writes: read `docs/dev-images-table-refresh-plan.md`; verify `SUPABASE_URL` is dev; run dry-run; inspect report; pause before write.
- Taxonomy: ignore image-table clothing labels; use page title/breadcrumb/browser-derived evidence; package for dashboard approval unless explicitly approved to write.
- Image-review dashboard: verify `/api/parts`; reset invalid bucket/part state; keep source workbooks immutable.
- Mobile review: rescan `human_labeled_returns`; create a fresh versioned folder; rely on import/export recovery.
- Scraping: check `_claims`, completed claims, existing outputs, S3, and triage docs before probing.
- Transcript: build compact JSON in `/private/tmp`; upload with `scripts/upload-codex-chat-transcript.mjs`; read back by `chat_key`.
- Git: stage only task-owned files; leave active claim files and unrelated dirty files alone.
- S3: use `FWM_AWS_PROFILE=fwm` unless current machine docs prove otherwise; verify identity before relying on sync.

## Query Notes

The transcript table can be queried with:

```js
fetch(
  process.env.SUPABASE_URL +
    "/rest/v1/codex_chat_transcripts" +
    "?select=chat_key,title,source,transcript_started_at,message_count,context_summary,context_summary_json,full_text" +
    "&order=transcript_started_at.desc.nullslast" +
    "&limit=1000",
  {
    headers: {
      apikey: process.env.SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY}`,
    },
  },
);
```

Do not put service-role keys in repo files or reports.
