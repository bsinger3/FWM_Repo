update staging.product_pages
set
  product_title_raw = initcap(regexp_replace(regexp_replace(normalized_product_page_url, '^https?://(www[.])?([^/]+)/goods/-?([0-9]+)$', '\2 product \3'), '[._-]+', ' ', 'g')),
  category_evidence = coalesce(category_evidence, 'product URL provided category signal; title reconstructed from source URL'),
  needs_manual_review = true,
  updated_at = now()
where product_title_raw is null or btrim(product_title_raw) = '';
