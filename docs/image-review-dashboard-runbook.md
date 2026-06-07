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

## Use From A Phone Without Publishing It

The dashboard is still a local web app. Do not deploy it publicly unless authentication is added first.

### Private USB Option

This keeps the source workbooks and generated return workbooks on the Mac, but lets Chrome on an Android phone open the dashboard over a USB cable. Nothing is published to the internet.

On the Mac:

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
npm run image-review
```

With Android Platform Tools installed and the phone connected by USB:

```bash
adb reverse tcp:4173 tcp:4173
```

Then open this in Chrome on the phone:

`http://127.0.0.1:4173/`

If the phone disconnects or Chrome cannot reach the page, reconnect USB and run the `adb reverse` command again.

### True Phone-Local Option

This runs the dashboard server on the phone itself. It is more self-contained, but the workbook package is large and generated returns must later be copied or synced back from the phone.

High-level setup:

1. Install Termux on the phone.
2. In Termux, install Node.js.
3. Copy the repo dashboard files and review workbook folders to phone storage.
4. Run `npm install`.
5. Run `npm run image-review`.
6. Open `http://127.0.0.1:4173/` in Chrome on the phone.

For normal review work, the private USB option is simpler because it keeps all workbook reads and exports on the Mac.

### Offline Train Option

Use this when the phone will not stay connected to the Mac and you do not want to publish the dashboard on the internet. The Mac prepares a static phone bundle with review rows and downloaded image files. The phone keeps progress in Chrome storage and exports a JSON decisions file. When you are back on the Mac, import that JSON file to generate the normal workbooks under `human_labeled_returns/`.

Build one part:

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
npm run image-review:mobile-bundle -- --parts needs_human_review:001 --skip-missing-images --require-images
```

Build several parts for a longer review session:

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
npm run image-review:mobile-bundle -- --parts needs_human_review:001,approve_candidates:001,disapprove_candidates:001 --skip-missing-images --require-images
```

The generated folder is:

`outputs/02_supabase_needs_human_review_cv_first_pass/mobile_review_bundle/`

For Android Chrome, prefer the generated single-file app, not the multi-file folder. Copy the versioned `v###_fwm_review_*.html` file to the phone and open it in Chrome. Progress is remembered in Chrome on the phone for that generated bundle.

The mobile dashboard batches phone-local progress writes. Card taps update the screen immediately, then Chrome local storage is flushed after about 50 changes, on bulk actions, when you tap `Export`, and when Chrome backgrounds or closes the page.

Simple Mac-to-Galaxy copy path:

1. Install Android File Transfer, OpenMTP, or another Android file-transfer app on the Mac if the phone does not appear in Finder.
2. Plug the Galaxy into the Mac.
3. On the phone, choose the USB mode for file transfer if Android asks.
4. Copy the versioned single-file HTML app into `Internal storage/BrisApps/`.
5. On the phone, open Chrome.
6. In Chrome, open the copied versioned HTML file.

When you are done reviewing on the phone, tap `Export`. Chrome downloads a file named like:

`fwm_mobile_review_decisions_YYYYMMDDTHHMMSSZ.json`

On Android Chrome, the web app may not be allowed to silently write straight into `BrisApps/FWM_Image_Review/returns_to_laptop`. The app tries to use a native save-file picker when the browser supports it. If Chrome falls back to a normal download, move the JSON file from `Download/` to:

`BrisApps/FWM_Image_Review/returns_to_laptop/`

Copy that JSON file back to the Mac, then import it:

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
npm run image-review:import-mobile -- /path/to/fwm_mobile_review_decisions_YYYYMMDDTHHMMSSZ.json
```

That import writes the usual return workbooks and manifest entries into:

`outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns/`

Notes:

- The phone bundle does not edit source workbooks.
- The phone bundle does not generate Excel workbooks directly. The Mac import step does that.
- For single-file phone bundles copied through OpenMTP, put the version at the front of the filename, for example `v001_fwm_review_unsaved_50_cards.html`, so the newest file is easy to spot in the phone file-transfer app.
- Build the bundle before leaving Wi-Fi so the images are downloaded into the folder.
- Use `--require-images` before travel. It makes the command fail if the bundle is not fully offline-ready.
- Use `--skip-missing-images` before travel if you would rather omit cards whose images cannot be downloaded locally instead of depending on intermittent internet.
- If you see `Offline ready: no`, some cards will not reliably render without internet access.
- If you see `Skipped rows: 12`, those 12 image rows were omitted from the phone bundle and should be reviewed later on the desktop dashboard.
- If the bundle is too large to copy comfortably, build fewer parts at once.
- The mobile grid targets about `188px` image cards. On a Galaxy S26 Ultra-sized display, that keeps each review image close to the desktop dashboard card size instead of stretching images larger in landscape.

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
