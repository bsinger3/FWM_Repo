# Step 4 CV Session Notes - April 14, 2026

This note captures the computer-vision work completed during the April 14, 2026
session against the Step 4 human review workflow.


## Changes Made

### 1. Added a second face-detection path for testing

A new script was added:

- `scripts/step_4_human_review_and_visibility_decisions/add_scrfd_face_column_to_workbook.py`

This script:

- reads a Step 4 review workbook
- downloads each image from `original_url_display`
- runs InsightFace `SCRFD` on CPU
- writes a new `has_face_scrfd` column next to `has_face_yunet`
- creates a `.bak` backup before saving the workbook

The goal of this test was to compare a stronger face detector with the existing
YuNet column rather than rely on a single face signal.


### 2. Updated the test workbook

The following workbook was updated in place:

- `data/step_4_human_review_and_visibility_decisions/manual_chunks/images_to_approve_part_001_SORTED.xlsx`

Result:

- added `has_face_scrfd`
- kept existing manual approval decisions unchanged
- left the new cell blank when the source image URL failed to download

Run summary from the session:

- `559` rows marked `true`
- `2431` rows marked `false`
- `12` rows left blank because the source image URL returned `404` or the
  connection reset during fetch


### 3. Added workbook-only YOLO pose columns for approval testing

A second test script was added:

- `scripts/step_4_human_review_and_visibility_decisions/add_yolo_pose_columns_to_workbook.py`

This script updates only a selected review workbook and adds these columns:

- `person_count_yolo_pose`
- `main_person_height_pct_yolo_pose`
- `main_person_bbox_area_pct_yolo_pose`
- `body_coverage_score_yolo_pose`

These fields were added only to:

- `data/step_4_human_review_and_visibility_decisions/manual_chunks/images_to_approve_part_001_SORTED.xlsx`

The purpose of this pass was to compare four higher-value composition signals
against the manual approval column before running anything across the rest of
the review chunks.

Initial directional results against manual approval labels:

- approved rows averaged higher `main_person_height_pct_yolo_pose`
- approved rows averaged much higher `body_coverage_score_yolo_pose`
- rejected rows contained many more `person_count_yolo_pose = 0`
- `main_person_bbox_area_pct_yolo_pose` had weaker separation than the other
  three new fields


## Findings From Approved vs Rejected Sample Review

A random sample of approved and not-approved images was reviewed against the
manual column:

- `image_approved? (1=Approved,2=NotApproved)`

Patterns observed in approved images:

- usually a single person
- usually an on-person try-on or mirror-selfie style photo
- the wearer is close enough to the camera to read the garment
- enough of the body is visible to understand the outfit in context

Patterns observed in rejected images:

- more than one person or ambiguous subject
- subject too far from the camera
- close-up crop of a body part or garment detail only
- partial-body framing such as butt-only, waist-only, or ankle-only
- product-only, laid-flat, or measurement-style photos


## Decision Rules Clarified During the Session

The user clarified that images may be manually rejected for any of the
following reasons:

- more than one person in the shot
- person too far away from the camera
- only part of the body visible, even if the garment is being worn

These clarified rules are more aligned with subject clarity and framing than
with face presence alone.


## Recommended Next Columns To Prioritize

The next CV columns should target the reasons images are actually rejected.

Priority order:

1. `person_count`
2. `main_person_height_pct`
3. `main_person_bbox_area_pct`
4. `body_coverage_score`

Recommended models:

- use a modern `YOLO` person detector for:
  - `person_count`
  - `main_person_height_pct`
  - `main_person_bbox_area_pct`
- use `MediaPipe Pose` for:
  - `body_coverage_score`
  - later derived fields such as `head_visible`, `knees_visible`,
    `ankles_visible`, and `feet_visible`

Reasoning:

- `person_count` directly supports the automatic rejection rule for multiple
  people
- subject-size columns provide the cheapest proxy for "too far away"
- pose/coverage signals are better suited than face detection for spotting
  butt-only, ankle-only, and other partial-body crops


## Recommended Automation Order

Suggested implementation order for the next round:

1. add `person_count` using a stronger person detector
2. derive `main_person_height_pct` and `main_person_bbox_area_pct` from the
   same person boxes
3. validate those columns against the manual approval column
4. add `body_coverage_score` from pose landmarks
5. only then decide whether a custom crop-type classifier is needed


## Scope Notes

This session did not automate final approval decisions.

The work completed here was:

- research and model selection
- one new face-detector test column
- manual sample review against the existing approval labels
- prioritization of the next highest-value CV columns
