# Step 5 Publish Ready Outputs

Step 5 contains only publish-ready outputs that have passed the human approval
gate.

## Source Of Truth

The authoritative Step 5 format is defined by:

- `images_intake_sample.xlsx`

In that workbook:

- `sampleOutput1` is the exact target output shape for this workflow
- `contraints` documents the field expectations and constraints

Generation rule:

- Step 5 must be derived from Step 4
- only rows with `Approved for publishing = 1` are kept
- rows without that value are removed
- the `Approved for publishing` column itself is removed before export
- the resulting output must match the `sampleOutput1` structure

Export rule:

- Step 5 files must be formatted for direct DBeaver upload
- the import workflow is documented in `dbeaver_import_workflow.docx`
- during import, `created_at_display` and `id` are present in the file shape
  but are skipped in DBeaver according to the documented workflow

Current state:

- this folder should remain empty until the final human approval process is
  complete
