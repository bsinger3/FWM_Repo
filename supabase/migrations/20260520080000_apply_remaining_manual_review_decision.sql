-- Apply the final completed row from the 2026-05-20 manual category review sheet.
-- A decision of 0 means the previously observed clothing type is correct.

update staging.product_pages
set
  mother_category_id = 'tops',
  product_category_raw = 'shirt',
  category_evidence = 'manual review: old observed clothing type accepted',
  category_confidence = 'high',
  needs_manual_review = false,
  raw_metadata = coalesce(raw_metadata, '{}'::jsonb) || jsonb_build_object(
    'manual_review_decision', '0',
    'manual_reviewed_at', now()
  ),
  updated_at = now()
where id = 'cabaf852-cc80-4d34-99b6-294237a9ea4d'::uuid;

delete from staging.product_page_clothing_type_tags
where product_page_id = 'cabaf852-cc80-4d34-99b6-294237a9ea4d'::uuid;

insert into staging.product_page_clothing_type_tags (product_page_id, clothing_type_id)
values
  ('cabaf852-cc80-4d34-99b6-294237a9ea4d'::uuid, 'shirt'),
  ('cabaf852-cc80-4d34-99b6-294237a9ea4d'::uuid, 'tops')
on conflict do nothing;
