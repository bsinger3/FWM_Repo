# CV vs Manual Approval Report: images_to_approve_part_001_SORTED.xlsx

## Scope

- workbook: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/amazon/data/step_4_human_review_and_visibility_decisions/manual_chunks/images_to_approve_part_001_SORTED.xlsx`
- sheet: `images_to_approve_part_001`
- manual label column: `image_approved? (1=Approved,2=NotApproved)`
- labeled rows analyzed: `2978`
- approved rows: `1893`
- rejected rows: `1085`

## Strongest Single-Column Signals

- `body_coverage_score_yolo_pose`: balanced accuracy `0.813`, raw accuracy `0.842`, best rule `body_coverage_score_yolo_pose` >= `66.7`
- `main_person_height_pct_yolo_detect`: balanced accuracy `0.714`, raw accuracy `0.771`, best rule `main_person_height_pct_yolo_detect` >= `0.503`
- `main_person_bbox_area_pct_yolo_detect`: balanced accuracy `0.706`, raw accuracy `0.766`, best rule `main_person_bbox_area_pct_yolo_detect` >= `0.121`
- `person_count_yolo_detect`: balanced accuracy `0.702`, raw accuracy `0.767`, best rule `person_count_yolo_detect` >= `1`
- `main_person_height_pct_yolo_pose`: balanced accuracy `0.654`, raw accuracy `0.737`, best rule `main_person_height_pct_yolo_pose` >= `0.558`

## Metric Summary

| metric | rows | approved mean | rejected mean | gap | best balanced acc. | best rule |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `body_coverage_score_yolo_pose` | 2964 | 78.532 | 33.251 | 45.281 | 0.813 | `body_coverage_score_yolo_pose` >= `66.7` |
| `person_count_yolo_detect` | 2964 | 1.064 | 0.618 | 0.446 | 0.702 | `person_count_yolo_detect` >= `1` |
| `main_person_height_pct_yolo_detect` | 2964 | 0.800 | 0.455 | 0.345 | 0.714 | `main_person_height_pct_yolo_detect` >= `0.503` |
| `person_count_yolo_pose` | 2964 | 1.094 | 0.823 | 0.271 | 0.639 | `person_count_yolo_pose` >= `1` |
| `main_person_height_pct_yolo_pose` | 2964 | 0.850 | 0.621 | 0.229 | 0.654 | `main_person_height_pct_yolo_pose` >= `0.558` |
| `has_face_scrfd` | 2964 | 0.269 | 0.048 | 0.220 | 0.610 | `has_face_scrfd` >= `1` |
| `main_person_bbox_area_pct_yolo_detect` | 2964 | 0.489 | 0.343 | 0.146 | 0.706 | `main_person_bbox_area_pct_yolo_detect` >= `0.121` |
| `main_person_bbox_area_pct_yolo_pose` | 2964 | 0.538 | 0.491 | 0.047 | 0.647 | `main_person_bbox_area_pct_yolo_pose` >= `0.121` |

## Blank Metrics

- present but blank for all labeled rows: `has_face_blazeface`, `body_coverage_score_mediapipe_pose`, `head_visible_mediapipe_pose`, `shoulders_visible_mediapipe_pose`, `hips_visible_mediapipe_pose`, `knees_visible_mediapipe_pose`, `ankles_visible_mediapipe_pose`, `feet_visible_mediapipe_pose`
