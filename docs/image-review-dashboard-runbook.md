# Image Review Dashboard Runbook

## Start The Dashboard

Open a terminal and run:

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
npm run image-review
```

Then open:

`http://localhost:4173/`

Keep the terminal running while you review images. Stop it with `Ctrl+C` when you are done.

## Important

Use the localhost URL, not the local `index.html` file path. The dashboard needs the local server so it can read the source workbooks and write generated return workbooks.

The dashboard reads source workbooks from:

`outputs/02_supabase_needs_human_review_cv_first_pass/partial_170000_rows_cv_gated/`

It writes generated human-labeled returns to:

`outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns/`

The source workbooks are not edited in place.

## Resume Reviewing

When you reopen the dashboard, it reloads saved decisions from:

`outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns/human_labeled_returns_manifest.json`

Use `Hide saved` to show only cards that still need review.

Use `Hide duplicates` to show one representative card per repeated image in the current part. Decisions on the representative apply to the duplicate rows in that loaded part.

## Export Progress

Click `Save progress / export decisions` to write new return workbook files under `human_labeled_returns/`.

Click `Undo last export` only if you need to pull back the most recent export. It deletes only the generated files for that latest export and restores those decisions as unsaved editable choices in the dashboard.
