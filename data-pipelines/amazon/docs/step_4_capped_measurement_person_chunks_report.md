# Step 4 Capped Measurement Person Chunks Report

This report describes the derived Step 4 chunk set created for upload preparation.

Filter rules:

- keep only rows where `has_person = true`
- remove rows where `exceeds_cap = 1`
- keep only rows with at least one measurement value
- preserve the Step 4 column layout

- source rows scanned: `91925`
- rows kept after filtering: `56649`
- output chunk count: `19`
- output folder: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/amazon/data/step_4_human_review_and_visibility_decisions/capped_measurement_person_chunks`

