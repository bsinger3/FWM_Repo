# Notes for Bri — 22 June 2026

Hi Bri — here's where things stand after today's session. **Nothing was written to
the dev database.** Everything is saved on disk and safe to shut down. Pick back up
from "What's next" whenever you're ready.

---

> **Heads-up — this file now covers TWO parallel sessions.** The original notes
> below are about the **extraction-audit / dev-database** work (all dry-run, nothing
> committed). A **separate** session (this one) built the **pre-fill-from-URL** site
> feature and **committed it to git locally** — see section 0 directly below. The
> "nothing committed" framing in the rest of this doc applies to the dev-DB work, NOT
> to the pre-fill feature.

---

## What we accomplished today

### R. Reddit post harvester (Claude Code — file-only, NOTHING committed, NOTHING in DB)

> This is a **separate session** from the Amazon-taxonomy / pre-fill / dev-DB notes
> below. It is **100% file-only**: nothing committed to git, nothing written to dev
> or prod Supabase. Safe to shut down.

**The goal:** find Reddit posts where people ask for clothing/fit help and include
their body measurements (and/or a photo), so we can later match them to the catalog
and reply with personalized suggestions.

**Where it stands:** **1,169 clean posts** harvested across 19 real fashion/fit
subreddits; **~374 have parsed measurements** (height, weight, bra size, bust,
waist, hips, inseam). A browsable **review dashboard** is built so you can eyeball
every post + field before we load anything.

**Open the dashboard (Chrome):**
```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
open -a "Google Chrome" .codex_tmp/reddit_review.html
```
Click any row to expand ALL captured fields (full text, measurements + exact matched
substrings, every image with thumbnail + HTTP status, author, flair, timestamps).
Controls: search, subreddit filter, "measured only"/"has image only", and a **sort
dropdown (Newest first / Oldest / Subreddit / Most measurements / Most images)**.

**Key constraints we hit:**
- Reddit's API is dead to us (2026 "Responsible Builder Policy" blocks new script
  apps; `.json` returns 403). The working path is the **public RSS feed**
  `r/<sub>/new/.rss` — no auth, rate-limited (~1 req/min), so the harvester paces.
- **RSS doesn't include flair**, so flair is scraped from old.reddit HTML separately.

**Bugs we found & fixed today (you caught most of these — great eye):**
- cm measurements stored as inches (e.g. "bust 106 cm" → 106") → now converted + bounds-checked.
- stray numbers parsed as weight → sanity bounds (70–500 lbs).
- **r/curvy and r/petite are PORN subs, not fashion** → removed from rotation, 198 posts purged, NSFW filter strengthened.
- bra size "28I" from "F 28 I need…" (pronoun) and age tags like "28F" → context-aware bra parsing.
- bra size missed on lowercase "32d" → case-insensitive + "boobs/breasts/bust" count as bra context.
- **flair was just the subreddit name** → new scraper pulls the REAL flair (e.g. "Recommendations?", "Question (5'1\"-5'4\")" — these even encode height brackets!).

**⏸ One job was mid-run when you shut down (resumable, no loss):** the flair
backfill reached **~200 / 1,164 posts**. Progress is checkpointed in
`FWM_Data/reddit_harvest/_state/flair.json`. To finish it when you're back:
```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
node scripts/enrich-reddit-flair.mjs --delay-ms=1800      # finishes the rest (~30 min)
node scripts/reparse-and-stats-reddit.mjs                 # re-applies parser + flows flair in
node scripts/build-reddit-review.mjs                      # rebuilds the dashboard
```

**Files (scripts in repo, UNCOMMITTED; data OUTSIDE repo in `FWM_Data/reddit_harvest/`):**
- `scripts/harvest-reddit-posts.mjs` — RSS harvester (subreddit rotation inline)
- `scripts/enrich-reddit-flair.mjs` — flair backfill from old.reddit (resumable)
- `scripts/reparse-and-stats-reddit.mjs` — re-parse raw text + print stats
- `scripts/build-reddit-review.mjs` — generate the HTML dashboard
- data: `posts.ndjson` (raw), `posts_clean.ndjson` (what the dashboard reads),
  `posts.ndjson.bak-before-nsfw-purge` (backup), `_state/flair.json` (flair progress)

**Next steps (Reddit):**
1. Finish the flair backfill (commands above), then review the dashboard.
2. You flag any remaining bad parses (each becomes a rule).
3. **Then** load into dev `staging.reddit_posts` (migration already written; I did
   NOT load — per your "let me look first").
4. Later: catalog-match logic. Reality from the data — people rarely give a full
   measurement set (only ~2 posts had height+bust+waist+hips), so matching must work
   from partial data (usually **height + bra size**, plus inseam in the tall subs).
5. Git: tell me "commit the reddit work" and I'll commit just these 4 scripts.

---

### A. Amazon product-page taxonomy backfill (Claude Code — committed AND pushed)

> This is a **third** session, separate from the pre-fill and dev-DB notes below.
> Unlike those, **my work is committed to `main` and pushed to `origin`** (commits
> `c3f3f9d`, `3a6e2a7`, `09f86b8`). Database changes are **dev only**, and the taxonomy
> results are **dry-run — nothing promoted to the live DB yet.**

**The goal:** fill in categories for the ~4,498 Amazon product pages that had none —
for free (plain HTTP GET of `amazon.com/dp/{ASIN}`, no paid tools).

**Where it stands:** the backfill reached **~2,787 / 4,498 (62%)** before you shut down.
**Nothing is lost** — it saves every page and resumes from where it stopped.

**Wins:**
- **Breadcrumb tie-breaker** (the big one): pages that were "ambiguous" because the rules
  tied (e.g. *"Boot Cut Pants"* → shoes or bottoms?) are now settled by the Amazon
  breadcrumb (`… > Pants`). **Auto-solved 172 of 226 ambiguous (76%)** — free, no AI —
  and it improves all future scrapes too.
- Your **manual-review pile dropped 302 → ~137**.
- We now keep the **full breadcrumb path** (new dev column `category_breadcrumb_path`) so
  you can filter by subcategory later, not just the high-level bucket.
- The backfill now **auto-retries blocked pages** when it finishes.
- You asked about a browser emulator for blocked pages — **tested, it doesn't help**
  (the block is IP rate-limiting; a browser shares the same IP). Retrying later / from a
  fresh network is the fix, and that's now automatic.

**Your review dashboard** for the ~137 leftovers:
```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
npm run amazon-taxonomy-review      # then open http://localhost:4176
```
Each row has an **"Open on Amazon"** button + **dropdowns** (category / clothing type /
breadcrumb). **It autosaves into the repo** (`data-pipelines/products/manual_taxonomy_review/`)
— no Downloads folder, stop/reopen anytime.

**What to do when you're back (Amazon taxonomy):**
1. **Resume the backfill** in a Terminal tab (~1–2 hrs; don't close the lid — that
   sleeps the Mac):
   ```bash
   cd /Users/briannasinger/Projects/FWM/FWM_Repo
   caffeinate -is node scripts/backfill-amazon-taxonomy-free.mjs --delay-min-ms=4000 --delay-max-ms=8000
   ```
   It finishes the rest, auto-retries blocked pages, and writes the final report with the
   tie-break applied. Check progress from a second tab:
   ```bash
   F=/Users/briannasinger/Projects/FWM/FWM_Data/_reports/amazon_taxonomy_worklist_20260619T182108730Z_progress.ndjson; D=$(wc -l < "$F"); echo "last write $(( $(date +%s) - $(stat -f '%m' "$F") ))s ago | done $D/4498 | remaining $((4498-D))"
   ```
2. **Review the ~137 leftovers** in the dashboard whenever you like.
3. **When happy**, ping me to promote the results into the dev DB (a separate,
   human-approved step — nothing auto-writes).

**One unverified item:** the live end-to-end test of the auto-retry was blocked by a
brief Anthropic infra hiccup (it gated that one network test command). Logic is reviewed
and its parts are individually proven; I'll confirm it live next session.

---

### 0. Pre-fill-from-URL site feature (NEW — committed to git, NOT pushed)
A shareable link can now carry someone's measurements so the site opens with the
search form pre-filled and the search already run — for one-click personalized
Reddit replies.

**Example link:**
```
https://friendswithmeasurements.com/?h_ft=5&h_in=5&weight=140&bust=34&cup=C&waist=29&hips=39
```
Add `&req=height,waist,hips` to also tick the "require this measurement" boxes.
Param names (`h_ft, h_in, weight, bust, cup, waist, hips, req`) are **locked** to
the `staging.reddit_posts.match_query_url` column — don't rename them. A visitor
with no params sees the normal site, unchanged.

**A bug we caught and fixed:** your first test showed the random gallery instead of
real matches — a **race** between the page's always-on `loadRandomResults()` and the
new auto-search. Fixed: `prefillFromQuery()` now owns the decision (search if
measurements present, else load the random gallery). No more race.

**⚠️ Git state — READ before pushing.** Local `main` is **3 commits ahead of
`origin/main`. NOTHING is pushed**, so the LIVE site is unchanged.

| Commit | Mine? | What |
|---|---|---|
| `7d4e8f1` | ✅ | Fix pre-fill auto-search race |
| `0683fbf` | ❌ **not mine** | "prettiness scorer v3" (another session, pre-existing) |
| `8acce26` | ✅ | Add pre-fill-from-URL feature |

- `0683fbf` is **not my work** — if you `git push`, it goes out too. Decide first.
- **Pushing `main` very likely triggers a Cloudflare Pages production deploy.** I did
  NOT push, on purpose — your call.
- `index.dev.html` and `.claude/launch.json` are **gitignored** (local-only); the dev
  copy has the same logic for testing, production ships from `index.html`.
- The working tree still shows lots of OTHER uncommitted changes from prior sessions
  — I committed ONLY my pre-fill hunks via targeted patches and left the rest alone.

**To re-test when you're back:**
```
node scripts/test-server.mjs        # serves index.html on http://localhost:4322
```
Open the example link above (hard-refresh) → expect real matches, not the random
gallery. Open plain `http://localhost:4322/` → expect the normal site (empty form,
sidebar open, no auto-search).

**Then decide the push:** all 3 commits (incl. the not-mine prettiness one) + deploy,
only the pre-fill commits, or keep waiting. Just tell me.

---

### 1. Rebuilt the measurement extraction-audit dashboard (your 3 requests)
`tools/extraction-audit-dashboard/` — start it with **`npm run extraction-audit`**
(opens on port 4175).

- **"Correctly extracted" mark.** Each comment now has **✓ Correct** and
  **⚑ Incorrect** buttons (was just a flag). Both save per-comment so you never see
  a judged comment again.
- **Already-reviewed comments are hidden.** Default view is **"Unreviewed only"** —
  anything you've marked (correct *or* incorrect) drops out. A status dropdown lets
  you revisit *Reviewed: correct / incorrect / All* when you want. Marking a card
  removes it instantly and the queue advances without skipping or repeating rows.
- **Extractions are from the CURRENT regexes.** The builder now re-runs the live
  Python parser on each comment instead of showing stale workbook values, and the
  panel is labeled "EXTRACTED MEASUREMENTS (LIVE REGEX)". It now also shows **Age**
  and **Pregnancy (weeks)** as measurements.
- Your 35 previously-flagged comments were migrated to "incorrect" and are hidden
  by default. **Note:** their extractions are now the *fixed* ones, so most are
  probably correct now — if you want, switch the filter to **"Reviewed: incorrect"**
  and flip the fixed ones to "Correct" to clear them.
- To refresh after any future regex change: **`npm run extraction-audit:build`**
  (needs `python3` on PATH; takes ~3 min).

### 2. Built + verified the write-back of corrected measurements to dev images
The improved regexes (from earlier today) corrected **10,918 comments**
(~5,500 measurements newly filled, ~8,300 column-shift garbage values dropped).
Today I built the path to push those corrections into dev `public.images`:

- **`npm run dev-images:measurement-overrides`** → builds
  `FWM_Data/_reports/extraction_audit/measurement_overrides.json`
  (26,729 comments → corrected height/weight/waist/hips/bust/bra-band/cup/inseam).
- The dev-images loader (`scripts/load-dev-approved-images.mjs`) now takes a
  `--measurement-overrides=PATH` flag. It matches each image to its comment and
  swaps in the corrected measurements; falls back to the workbook otherwise.
- **I did NOT touch the 326 review workbooks** — rewriting them risks stripping the
  `image_preview` cells. The override file is the safe, reversible route.
- **Dry-run verified (nothing written):** corrections applied to **27,773** of the
  39,734 approved image rows. Example that now lands correctly: a review saying
  *"32,29,45 are my measurements… 5'7… 150lbs"* had empty bust/waist/hips in the
  workbook → now bust 32 / waist 29 / hips 45.

---

## What's next (your decision when you're back)

**Deciding question:** apply the corrected measurements to the dev database.
The dry-run showed it would update **~33,000 dev image rows** but quarantine
**7,000 rows** that have a *pre-existing* duplicate-image-URL conflict (unrelated to
this work — their corrections won't land until those conflicts are sorted out
separately). It's reversible on dev (`npm run dev-images:baseline:restore`).

You were mid-answer on this when you had to step away. Three paths:

1. **Apply now (skip the 7,000 conflicts).** Run:
   ```
   FWM_DEV_IMAGE_LOAD_SKIP_DUPLICATE_CONFLICTS=yes-reviewed-dry-run \
   node scripts/load-dev-approved-images.mjs --apply --resolve-workbooks \
   --measurement-overrides=/Users/briannasinger/Projects/FWM/FWM_Data/_reports/extraction_audit/measurement_overrides.json
   ```
   Writes corrected measurements to the ~33k rows; the 7,000 conflicts stay unchanged.

2. **Hold** — leave it staged (current state). Nothing written.

3. **Investigate the 7,000 duplicate conflicts first** so those corrections can land
   too, instead of being quarantined.

Just tell me which and I'll take it from there.

### Smaller follow-ups noted
- **Age isn't propagated to dev yet.** `public.images.age_years_display` exists, but
  the loader's database function (RPC) doesn't accept age, so age corrections (+299
  comments) stop at the override file. Wiring age through needs a small RPC change —
  separate task if you want it.
- The "Reviewed: incorrect" cleanup pass on your old 35 flags (see section 1).

---

## State of things / safety
- **Nothing written to the dev or production database.** All dev writes are still
  dry-run only.
- Working tree changes are **not committed** (consistent with how this repo hands
  off between sessions — see `AGENT_LOG.md`, my 18:25 entry has the full detail).
  The new/changed files are saved on disk and will survive the shutdown:
  - `tools/extraction-audit-dashboard/` (dashboard v2 + `extract_batch.py`)
  - `scripts/build-measurement-overrides.mjs`
  - `scripts/load-dev-approved-images.mjs` (added `--measurement-overrides`)
  - `package.json` (new npm scripts)
- The dashboard server I had running has been stopped.
- A memory was saved so future audit dashboards include the "correct" mark +
  hide-reviewed + live-regex behavior by default.

Safe to shut down. 👋

---

# Part 2 — Prettiness score + auto-crop (another session today)

> **⚠️ Correction to any "nothing written to dev" lines above.** True for the
> measurement work — but **this** thread *did* write to the **dev** database: **157
> crop windows** (details below). Gated, verified, reversible. No production writes,
> no image-measurement rows touched.

### What got done
- **Prettiness scorer v3 — committed (`0683fbf`).** Adds a "technical quality" bucket
  — **lighting** (exposure / brightness / contrast / color-cast) plus a coarse
  **background-clutter** proxy — measured from the actual image pixels, on top of the
  existing domain-fit score. Technical is clamped to **25%** influence while the CLIP
  "aesthetic" piece is still pending, so domain-fit stays in charge. Dry-run only; it
  never writes image rows.
- **Auto-crop-aware scoring (your request).** The scorer can now measure
  lighting/clutter on the **cropped card** (taxonomy-aware crop window) instead of the
  full source image. Crops shed background, so clutter drops — tight garment crops
  score a bit prettier (~**+0.02** overall, **+0.09-0.11** on garment crops).
- **Applied the verified crop backfill to dev** — **157 crop windows** written to dev
  `public.images.crop_spec` (model `auto_crop_garment_aware_v1`). Safe path: dry-run ->
  passed verification report -> gated `--apply`. Verified after: the scorer now reads
  real crop windows from dev for those 157 rows with no special flags. Reversible.
- **Saved a preference to memory:** future review dashboards should have a **slider
  that filters visible images by prettiness score**, so you can watch the dash get
  "prettier" as you drag it (candidate for the live frontend later).

### What's blocked / next  <-- needs you
The **full** crop set first needs person-detection over all **45,269** crop-eligible
images. That run **keeps getting killed after ~1-2 min / a few hundred images** when
launched inside an agent session (the harness reaps long background jobs). **Not a
code bug** — it runs and resumes cleanly, it just can't survive in here. Progress:
**2,381 / 45,269 (~5%)**, saved and resumable.

**To finish it, run this in your OWN Terminal** — detaches, survives on its own, keeps
the Mac awake, auto-resumes (~5h):
```
cd /Users/briannasinger/Projects/FWM/FWM_Repo
caffeinate -is nohup ../FWM_Data/_venv_cv/bin/python scripts/detect_person_boxes.py \
  --input ../FWM_Data/_cache/crop_worklist.ndjson \
  --output ../FWM_Data/_cache/crop_bboxes_full.ndjson \
  --detect-model ../FWM_Data/_models/yolov8n.pt \
  --pose-model ../FWM_Data/_models/yolov8n-pose.pt --resume \
  > ../FWM_Data/_cache/detect_run.log 2>&1 &
```
Watch with `tail -f ../FWM_Data/_cache/detect_run.log` (counts up to `/43320`). When
it finishes, tell me and I'll run the full crop backfill the same gated way; the
scorer then reads crop windows for the whole set automatically.

### Safety / state (this thread)
- **Dev DB:** 157 crop windows written (gated + verified + reversible via crop
  baseline). No production writes. No image-measurement rows touched here.
- **Git:** prettiness scorer committed `0683fbf` on local `main` (not pushed).
- **Nothing running now.** Detection process stopped; 2,381-row output intact and
  resume-ready (last line verified valid).

Safe to shut down. -- Claude (prettiness/auto-crop thread)
