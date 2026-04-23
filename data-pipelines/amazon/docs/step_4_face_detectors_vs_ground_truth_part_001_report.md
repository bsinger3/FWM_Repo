# Face Detector vs Ground Truth Report: images_to_approve_part_001_SORTED.xlsx

## Scope

- workbook: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/amazon/data/step_4_human_review_and_visibility_decisions/manual_chunks/images_to_approve_part_001_SORTED.xlsx`
- sheet: `images_to_approve_part_001`
- ground truth column: `has_face_GroundTruth (1=face,2=noFace)`
- GT-labeled rows analyzed: `3000`

## Detector Ranking

- `has_face_yunet`: accuracy `0.972`, precision `0.851`, recall `0.987`, specificity `0.969`, F1 `0.914`
- `has_face_scrfd`: accuracy `0.957`, precision `0.789`, recall `0.980`, specificity `0.953`, F1 `0.874`
- `has_face_opencv_dnn_ssd`: accuracy `0.941`, precision `0.918`, recall `0.670`, specificity `0.989`, F1 `0.774`

## Confusion Summary

| detector | rows | accuracy | precision | recall | specificity | F1 | TP | FP | TN | FN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `has_face_yunet` | 2994 | 0.972 | 0.851 | 0.987 | 0.969 | 0.914 | 445 | 78 | 2465 | 6 |
| `has_face_scrfd` | 2986 | 0.957 | 0.789 | 0.980 | 0.953 | 0.874 | 441 | 118 | 2418 | 9 |
| `has_face_opencv_dnn_ssd` | 2994 | 0.941 | 0.918 | 0.670 | 0.989 | 0.774 | 302 | 27 | 2516 | 149 |

## Missing Columns

- detector columns not present in the workbook: `has_face_retinaface`

## Blank Columns

- present but blank for all GT-labeled rows: `has_face_blazeface`
