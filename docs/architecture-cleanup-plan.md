# Architecture clean-up plan

Status: draft, 2026-06-19. Owner: Bri. Drafted with Claude Code.

This plan is about **legibility and boundaries**, not a rewrite. The codebase
works; the goal is to make its structure tell its own story and to retire the
few places where manual discipline stands in for a real mechanism.

It explicitly respects two in-flight, intentional things:

- **`index.dev.html`** is not stale drift — it's the testbed for a from-scratch
  v2 front end with much more sophisticated search, backed by the product-pages
  / taxonomy data the current `index.html` can't reach. Treat the two as
  prod (`index.html`) vs. the next site (`index.dev.html`).
- **`supabase/dev-migrations/`** is the v2 schema (incl. the product-pages
  table) being rebuilt alongside prod, to be promoted once it tests well. The
  prod/dev migration split and the two duplicated migration files are expected
  for now — this is a strangler-fig migration, not disorganization.

---

## 1. Where we actually are (corrected assessment)

An earlier quick read called the database logic "smeared across two languages."
On investigation that was wrong, and the truth matters for the plan:

- **Python (`data-pipelines/`, ~293 files / ~78k lines): zero direct DB access.**
  No `supabase` / `psycopg` / `asyncpg` imports anywhere. It reads and writes
  CSV/JSON/XLSX files only — scraping, cleaning, CV annotation, affiliate-link
  selection, measurement analysis. It is a pure file-in/file-out data factory.
- **Node (`scripts/`, ~37 files / ~11k lines): 100% of DB access.** All Supabase
  reads, writes, and migrations run through the `.mjs` scripts via `psql`
  (`scripts/lib/postgres-client.mjs`) and the Supabase REST wrapper
  (`scripts/lib/dev-supabase-guard.mjs`, which also enforces the dev/prod guard).
- **`tools/` dashboards (Node):** `taxonomy-review-dashboard` queries Postgres
  directly; `image-review-dashboard` is file-only (XLSX on disk).
- **The seam:** Python produces files → Node reads files → Node writes Supabase.
  Unidirectional, file-based. **This is a clean, low-coupling boundary, not a
  tangle.** The two runtimes barely know about each other.

So the real issues are narrower than "spaghetti":

1. **Two runtimes with an *unnamed* contract.** The Python↔Node boundary is
   clean but implicit — nothing documents "Python owns data production, Node
   owns the database + UI + tests," and the handoff file formats aren't a
   declared contract. The split is fine; its *invisibility* is the problem.
2. **The repo root has no top-level story** (see §3).
3. **`scripts/` is 40 flat files**, several of which are spent one-offs
   (`fix-dev-romper-jumpsuit-categories.mjs`, etc.) that should be archived.
4. **Root scratch clutter** (`temp_resumechat.rtf`, `scraped_asins_*.csv/.txt`,
   loose `*_report.md` / `*-plan.md`).

---

## 2. The textbook diagnosis (so we're using shared language)

Reference: *Fundamentals of Software Architecture: An Engineering Approach*,
Mark Richards & Neal Ford (O'Reilly). The "Modularity" chapter is **Chapter 3**
(Ch. 4 is "Architecture Characteristics Defined"). The chapter doesn't offer a
roster of cute nicknames — it offers **measures** of modularity and one named
anti-pattern:

- **Big Ball of Mud** (Foote & Yoder) — "a haphazardly structured, sprawling,
  sloppy, duct-tape-and-baling-wire, **spaghetti-code jungle**." A system with
  *no discernible architecture*. This single definition is where both phrases
  you remembered come from — "spaghetti" and "really mixed up, whatever" are two
  faces of the same Big Ball of Mud, not two separate labels.
- The measures it gives for judging a structure:
  - **Cohesion** — how related the parts inside a module are (best → worst:
    functional, sequential, communicational, procedural, temporal, logical,
    **coincidental** = grouped by accident).
  - **Coupling** — interdependence between modules (low is good).
  - **Connascence** — if changing one component forces a change in another to
    stay correct.

**Verdict for this repo:** it is **not** a Big Ball of Mud / spaghetti. The
pipeline has a clear directional spine (`00`→`04`), and the Python↔Node seam is
low-coupling. By the book's measures the *modules* score well. The one place the
pejorative genuinely applies is the **repo root**, which is **coincidental
cohesion** — the website, the pipeline, agent-comms docs, scratch files, and
build config sit as peers only because they happen to share a folder, not
because they belong together. That is the precise, narrow thing to fix.

---

## 3. Workstream A — a top-level story for the repo

Goal: someone landing at the root can name the ~6 zones and the data flow in 30
seconds (the same zones as the repo-map visualization).

Proposed top-level zones (names illustrative):

| Zone | Today | Holds |
| --- | --- | --- |
| Website | `index*.html`, `assets/`, `config*.js` | prod site + v2 dev site |
| Pipeline | `data-pipelines/` | Python data factory (`00`→`04`) |
| DB | `supabase/`, `database.types.ts` | schema, migrations, generated types |
| Ops | `scripts/` | Node DB/admin scripts |
| Review tools | `tools/` | local review dashboards |
| Experiments | `experiments/` | CV research sandbox |
| Docs | `docs/`, `*.md` agent comms | runbooks, plans, agent log |

Two ways to express the story (pick one in review):

- **Low-risk (recommended first):** keep paths where they are, add a
  `Repository map` section to `README.md` that names these zones, states the
  Python→files→Node→Supabase flow, and points out the prod-vs-v2 fork. This
  fixes the *legibility* problem without touching any path. Cheap, reversible.
- **Higher-risk (later):** physically regroup into top-level dirs. **Two hard
  constraints must be checked first:**
  - Cloudflare Pages serves the site from the repo root. Moving `index.html`
    into a `website/` dir requires changing the Pages "root directory" / output
    setting, or it breaks the live site. Do not move site files until that
    setting is confirmed and changed in tandem.
  - Moving `scripts/` breaks every `npm run` path in `package.json`; those must
    be updated in the same change.

Start with the README map. Only do the physical move if the README alone
doesn't make the structure obvious enough.

---

## 4. Workstream B — runtime / language strategy

**Gate: do not start until Codex answers the question in `AGENT_LOG.md`** about
why the DB layer landed in Node. The answer decides between two options.

The polyglot is partly forced and won't fully disappear either way: CV/scraping
is Python-native; the review dashboards and Playwright tests are Node-native. So
"one language for everything" is not on the table. The real choice is **where
the database boundary sits**:

- **Option B1 — Formalize the seam (current lean).** Declare it: *Python = data
  production (everything up to a publish-ready file); Node/TS = database access,
  UI, and tests.* Write the handoff file formats down as a contract (column
  schemas / JSON shapes in `data-pipelines/schemas/`). No migration of working
  code; we just name and document the boundary that already exists. Lowest risk,
  keeps each language where it's strongest.
- **Option B2 — Move DB access into Python.** Add `supabase-py`/`psycopg` so the
  pipeline writes Supabase directly and the ~11k lines of Node DB code retire.
  Unifies the data layer in one language — but you'd still keep Node for the
  dashboards and Playwright, so it doesn't end the polyglot, it just moves the
  seam. Higher effort, rewrites working code.

Recommendation to discuss: **B1 now** (it's mostly documentation + a guard that
the contract is honored), revisit B2 only if the file handoff later proves to be
a real source of bugs. Either way, Codex's rationale comes first.

---

## 5. Workstream C — hygiene (low risk, do anytime)

- Move root scratch to where it belongs: `temp_resumechat.rtf` (delete),
  `scraped_asins_saved_locally_*.csv/.txt` → `FWM_Data/_archive/`, loose
  `*_report.md` / `*-plan.md` / `*-context.md` → `docs/`.
- Archive spent one-off scripts (`fix-dev-*`, etc.) into `scripts/_archive/` (or
  delete — git keeps them) so `scripts/` only holds tools you'd run again.
- Leave the two duplicated migrations and the prod/dev split alone until the v2
  schema is promoted; revisit as part of that promotion, not now.

---

## 6. Sequencing

1. **Codex answers the runtime question** (`AGENT_LOG.md`) — unblocks §4.
2. **Workstream C hygiene** — clears the noise so structure is visible.
3. **Workstream A, README map** — names the zones and the data flow.
4. **Workstream B decision** — formalize the seam (B1) or plan the Python
   migration (B2), per Codex's rationale.
5. **(Optional, later) physical top-level regroup** — only after confirming the
   Cloudflare Pages root setting and updating `package.json` paths.

## Open questions

- Codex's reason for the Node DB layer (blocks §4).
- Cloudflare Pages: can/should the served root move to a subdir? (blocks the
  physical regroup in §3.)
- When is the v2 schema expected to promote? (sets when §5's migration cleanup
  happens.)
