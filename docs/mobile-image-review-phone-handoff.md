# Mobile Image Review Phone Handoff

## Phone App Folder

Put phone review apps here:

```text
Internal storage/BrisApps/
```

Single-file review apps should start with a version number so they are easy to find in OpenMTP:

```text
v001_fwm_review_unsaved_50_cards.html
v002_fwm_review_unsaved_50_cards.html
```

## Image Crop Behavior

The swipe card and grid card use the same production crop as the Friends With Measurements website card:

```css
aspect-ratio: 3 / 4;
object-fit: cover;
```

That means if the top of an item is cut off in the phone swipe card, it should also be cut off on the final website card. Tapping into the detail view shows the full image with `object-fit: contain`, which is only for inspection and should not be treated as the final website crop.

The phone app has two review modes:

- `Swipe`: one large production-crop card at a time, with right swipe for approve and left swipe for reject.
- `Grid`: smaller production-crop thumbnails. Tap a card to approve it, tap it again to return it to neutral. Use the card `i` button for detail/comments.

## Phone Return Folder

Move exported phone decisions here before copying back to the Mac:

```text
Internal storage/BrisApps/FWM_Image_Review/returns_to_laptop/
```

The exported file is named like:

```text
fwm_mobile_review_decisions_YYYYMMDDTHHMMSSZ.json
```

Android Chrome may download the JSON to:

```text
Internal storage/Download/
```

If that happens, use My Files on the phone to move it into:

```text
Internal storage/BrisApps/FWM_Image_Review/returns_to_laptop/
```

## Mac Phone-App Files

Generated phone HTML apps live under:

```text
/Users/briannasinger/Projects/FWM/FWM_Repo/outputs/02_supabase_needs_human_review_cv_first_pass/
```

Example:

```text
/Users/briannasinger/Projects/FWM/FWM_Repo/outputs/02_supabase_needs_human_review_cv_first_pass/v002_fwm_review_unsaved_50_cards.html
```

## Copy App To Phone With OpenMTP

1. Plug the phone into the Mac.
2. On the phone, set USB mode to `Transferring files / Android Auto`.
3. Open OpenMTP on the Mac.
4. Mac side: open:

```text
/Users/briannasinger/Projects/FWM/FWM_Repo/outputs/02_supabase_needs_human_review_cv_first_pass/
```

5. Phone side: open:

```text
Internal storage/BrisApps/
```

6. Drag the versioned HTML file from the Mac side to the phone side.
7. On the phone, open the HTML file from My Files. Use Chrome.

## Copy Returns Back To Mac With OpenMTP

1. Open OpenMTP.
2. Phone side: open:

```text
Internal storage/BrisApps/FWM_Image_Review/returns_to_laptop/
```

3. Mac side: open:

```text
/Users/briannasinger/Projects/FWM/FWM_Repo/outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns/
```

4. Drag the exported `fwm_mobile_review_decisions_*.json` file from the phone side to the Mac side.

## Import Phone Returns Into The Repo

After the JSON is copied into `human_labeled_returns/`, run:

```bash
cd /Users/briannasinger/Projects/FWM/FWM_Repo
npm run image-review:import-mobile -- outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns/fwm_mobile_review_decisions_YYYYMMDDTHHMMSSZ.json
```

This creates normal return workbooks under:

```text
/Users/briannasinger/Projects/FWM/FWM_Repo/outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns/
```

It also updates:

```text
/Users/briannasinger/Projects/FWM/FWM_Repo/outputs/02_supabase_needs_human_review_cv_first_pass/human_labeled_returns/human_labeled_returns_manifest.json
```

The source workbook files are not edited.
