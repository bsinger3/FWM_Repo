# Reddit Harvester — Session Handoff / Continuation Brief

**Purpose:** everything a *fresh* Claude Code session needs to continue the Reddit
post-harvesting work without the prior chat's context. Self-contained on purpose.

**Related docs (read if you need more):**
- `22June2026_NotesForBri.md` → section **R** — human-facing status of this work.
- `AGENT_LOG.md` → the `~18:40 EDT — Reddit harvester` entry — cross-agent handoff.
- `CLAUDE.md` — repo norms (two agents share this checkout; read AGENT_LOG first,
  append at session end; commit only when the human asks).

---

## 1. Mission

Friends With Measurements (FWM) matches people to clothing that fits their body.
This workstream **harvests Reddit posts where people ask for clothing/fit help and
include their body measurements (and/or a self-photo)**, so we can later match them
to the FWM image catalog and reply with personalized suggestions (goal: respond
within ~24h of a post).

Pipeline stage today: **collection + parsing + human review.** Nothing is in the
database yet and nothing is committed to git.

---

## 2. Current state (as of 2026-06-22)

- **1,169 clean posts** harvested across **19** real fashion/fit subreddits.
- **~374 posts have parsed measurements** (height, weight, bra size, bust, waist,
  hips, inseam), extracted from post text with unit conversion + sanity bounds.
- A **review dashboard** (`.codex_tmp/reddit_review.html`, gitignored) shows every
  post and every captured field for human QA.
- **Flair backfill is partial: ~200 / 1,164 posts.** Resumable (see §6).
- **NOT loaded** into dev `staging.reddit_posts` (migration written, task done) —
  waiting on human review of the dashboard first.
- All 4 scripts are **uncommitted working-tree changes**.

---

## 3. Hard constraints (learned the hard way — do not relitigate)

1. **Reddit's API is dead to us.** The 2026 "Responsible Builder Policy" disabled
   self-serve script-app creation; the human has no grandfathered key. The
   unauthenticated `https://www.reddit.com/...json` endpoints return **403**.
   → Do **not** build an OAuth path. The `.env.example` `REDDIT_CLIENT_*` keys are
   dead and uncreatable.
2. **Working data path = public Atom RSS:** `https://www.reddit.com/r/<sub>/new/.rss`
   — no auth. Gotchas: the trailing-slash form `/new/.rss` works (bare `/new.rss`
   returns an empty 200); **rate-limited ~1 req/min** (`x-ratelimit-remaining` → 0);
   requires a descriptive browser-like `User-Agent`.
3. **RSS does NOT contain link flair.** The Atom `<category>` is always the
   subreddit, never flair. Flair is scraped separately from **old.reddit HTML**
   (`https://old.reddit.com/r/<sub>/comments/<id>/`) — that returns 200 where `www`
   `.json` is 403. Flair lives in a `linkflairlabel` span (not the first span class);
   titles carry HTML entities like `&quot;`.
4. **r/curvy and r/petite are NOT fashion subs** — despite the names they're ~95%
   NSFW/solicitation. They were removed from rotation; keep them out. There is an
   NSFW/off-intent filter (`looksOffIntent`) — extend it, don't weaken it.

---

## 4. File map

**Scripts (in repo `scripts/`, all UNCOMMITTED):**
| File | Role |
|---|---|
| `harvest-reddit-posts.mjs` | RSS harvester; subreddit rotation list + relevance tiers are inline. Dedups via `_state/seen_ids.json`. |
| `enrich-reddit-flair.mjs` | Backfills real flair from old.reddit HTML. Resumable via `_state/flair.json`. `--delay-ms`, `--limit`. |
| `reparse-and-stats-reddit.mjs` | Re-applies the parser to stored `raw_text` (no re-fetch) → `posts_clean.ndjson` + prints summary stats. |
| `build-reddit-review.mjs` | Generates the HTML review dashboard → `.codex_tmp/reddit_review.html`. |

**Data (OUTSIDE the repo, sibling dir `../FWM_Data/reddit_harvest/`):**
- `posts.ndjson` — raw harvest (append-only, deduped).
- `posts_clean.ndjson` — cleaned/re-parsed; **this is what the dashboard reads**.
- `posts.ndjson.bak-before-nsfw-purge` — backup before curvy/petite removal.
- `_state/seen_ids.json` — harvest dedup state.
- `_state/flair.json` — flair backfill progress (~200 resolved).

**Record shape** (per post): `id`, `subreddit`, `title`, `permalink`, `author`,
`created_utc`, `flair` (null until backfilled), `raw_text`, `image_urls[]` (+ verify
status), `measurements{ height_in, weight_lbs, bra_size, bust_in, waist_in, hips_in,
inseam_in, raw[] }`. `measurements.raw[]` keeps the exact matched substrings so a
human can verify each parse.

---

## 5. Parser rules already implemented + gotchas

Measurement extraction is **heuristic** — always keep `raw_text` + `measurements.raw[]`
for human verification. Rules added so far (don't regress these):
- **cm → inch** conversion with per-field plausibility bounds (e.g. "bust 106 cm"
  must not store as 106").
- **Weight** bounds 70–500 lbs (drops stray numbers).
- **Height** handles `5'1"`, `5 ft 1`, `5'1`, cm.
- **Bra size** is the most false-positive-prone: case-insensitive (`32d`);
  multi-letter cups (DD, HH) are accepted alone; single-letter cups OR any space
  between band and cup require nearby bra context (`bra/cup/band/underbust/boobs/
  breasts/bust`); spaced single letters are rejected. This kills age/gender tags
  ("28F"), pronouns ("F 28 I need…" → "28I"), and stray words.

**Data reality that shapes matching:** people rarely give a full set — only ~2 posts
had height+bust+waist+hips together. The reliable signals are usually **height +
bra size** (plus **inseam** in the tall subs). Flair often encodes height brackets
(e.g. `Question (5'1"-5'4")`). Any matching logic must work from **partial** data.

---

## 6. Immediate next steps

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo

# 1. Finish the flair backfill (~30 min; resumable, safe to re-run)
node scripts/enrich-reddit-flair.mjs --delay-ms=1800

# 2. Re-parse + rebuild the dashboard
node scripts/reparse-and-stats-reddit.mjs
node scripts/build-reddit-review.mjs
open -a "Google Chrome" .codex_tmp/reddit_review.html
```

Then: **human reviews the dashboard and flags bad parses** (each becomes a rule)
**before** any database load.

---

## 7. Open work / decisions (not yet started)

1. **Load into dev `staging.reddit_posts`** (migration already written). Dev only —
   never prod. Only after human review. Includes a `match_query_url` column.
2. **Catalog-match logic** — match a post's partial measurements to FWM catalog
   images. Must handle missing fields gracefully.
3. **Pre-fill search link** — a separate task: a shareable URL that opens the FWM
   site (`index.html`) with the search form pre-filled from measurements, so replies
   can be one-click. **Locked param names** (contract with `match_query_url`):
   `h_ft, h_in, weight, bust, cup, waist, hips, req`. (A drafted prompt for this
   exists; another session may already be building it — check `index.html` /
   `index.dev.html` and `AGENT_LOG.md` before starting.)
4. **Scheduling** — run the harvester every few hours to stay inside the 24h window.

---

## 8. Ready-to-paste opening prompt for the new chat

> Continue the Friends With Measurements **Reddit post harvester**. Read
> `docs/reddit-harvester-handoff.md` first for full context, then `AGENT_LOG.md`.
> Current state: ~1,169 posts harvested to `../FWM_Data/reddit_harvest/`, ~374 with
> parsed measurements, flair backfill ~200/1,164 done (resumable). Nothing is in the
> database. Today I want to: **[finish the flair backfill and review the dashboard
> / load into dev staging.reddit_posts / build the catalog-match logic / …]**.
> Constraints: Reddit API is dead — RSS + old.reddit only; dev DB only, never prod;
> file-first; commit only when I ask.
