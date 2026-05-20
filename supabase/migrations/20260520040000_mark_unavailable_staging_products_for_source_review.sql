insert into staging.clothing_mother_categories
  (id, label, display_label, sort_order, frontend_sort_order, is_frontend_filter)
values
  ('source-review', 'Source Review', 'Source Review', 1000, 1000, false)
on conflict (id) do update set
  label = excluded.label,
  display_label = excluded.display_label,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  is_frontend_filter = excluded.is_frontend_filter,
  updated_at = now();

insert into staging.clothing_type_tags
  (id, mother_category_id, label, display_label, aliases, sort_order, frontend_sort_order, is_search_tag, is_frontend_filter, search_boost)
values
  ('archived-product-page-needs-review', 'source-review', 'Archived Product Page Needs Review', 'Archived Product Page Needs Review', array['unavailable product page'], 1000, 1000, false, false, 0)
on conflict (id) do update set
  mother_category_id = excluded.mother_category_id,
  label = excluded.label,
  display_label = excluded.display_label,
  aliases = excluded.aliases,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  is_search_tag = excluded.is_search_tag,
  is_frontend_filter = excluded.is_frontend_filter,
  search_boost = excluded.search_boost,
  updated_at = now();

update staging.product_pages
set
  product_title_raw = coalesce(
    nullif(product_title_raw, ''),
    initcap(regexp_replace(regexp_replace(normalized_product_page_url, '^https?://(www[.])?([^/]+)/.*?/([0-9]+)$', '\2 archived product \3'), '[._-]+', ' ', 'g'))
  ),
  mother_category_id = coalesce(mother_category_id, 'source-review'),
  product_category_raw = coalesce(product_category_raw, 'archived-product-page-needs-review'),
  category_evidence = 'source page unavailable; staged for source review rather than assigned to a clothing category',
  category_confidence = 'low',
  needs_manual_review = true,
  updated_at = now()
where
  product_title_raw is null
  or btrim(product_title_raw) = ''
  or mother_category_id is null;

insert into staging.product_page_clothing_type_tags (
  product_page_id,
  clothing_type_id,
  evidence
)
select
  id,
  'archived-product-page-needs-review',
  category_evidence
from staging.product_pages
where mother_category_id = 'source-review'
on conflict (product_page_id, clothing_type_id) do update set
  evidence = excluded.evidence;
