# Step 2 Standardization And Text Extraction

Step 2 converts raw Amazon scrape files into a standardized schema while also
extracting structured values from customer comments.

Responsibilities in this step:

- map source fields into the target sample-output column names
- normalize product and image URLs
- extract measurements, age, and related values from review text
- generate pre-approval normalized outputs

Important note:

- Step 2 outputs are not publish-ready
- Step 2 outputs still need image annotation and human approval later in the
  workflow

Current script responsibility:

- `regenerate_normalized_amazon_data.py` currently spans both standardization
  and text extraction, so both concerns are intentionally combined in this step

Current output location:

- `data/step_2_standardization_and_text_extraction/pre_approval_normalized_outputs/`
