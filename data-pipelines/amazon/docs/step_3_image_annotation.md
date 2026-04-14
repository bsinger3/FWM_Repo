# Step 3 Image Annotation

Step 3 enriches approval-batch image review files with machine-generated image
signals.

Current machine-generated review columns include:

- `has_person`
- `has_face_yunet`
- `lighting_ok`
- `full_lower_body_visible`

Step 3 data areas:

- `raw_inputs/`
- `machine_annotated_outputs/`
- `archive/`

Review-sheet rule:

- Step 3 should keep machine-generated review columns human-readable because
  they are consumed directly by human reviewers in Step 4

Quality rule:

- if a machine-generated column proves unreliable, it should be removed or
  replaced rather than preserved under a misleading name
