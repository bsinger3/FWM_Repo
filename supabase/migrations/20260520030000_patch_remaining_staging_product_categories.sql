insert into staging.clothing_type_tags
  (id, mother_category_id, label, display_label, aliases, sort_order, frontend_sort_order, search_boost)
values
  ('robe', 'sleepwear', 'Robe', 'Robe', array['robes'], 30, 30, 1.25),
  ('skort', 'bottoms', 'Skort', 'Skort', array['skorts'], 75, 75, 1.2),
  ('playsuit', 'jumpsuits-rompers', 'Playsuit', 'Playsuit', array['playsuits'], 45, 45, 1.2),
  ('pullover', 'tops', 'Pullover', 'Pullover', array['pullovers', 'quarter zip', 'quarter-zip', 'fleece pullover'], 86, 86, 1.15),
  ('henley', 'tops', 'Henley', 'Henley', array['henleys'], 87, 87, 1.15),
  ('fleece', 'outerwear', 'Fleece', 'Fleece', array['fleeces', 'full zip fleece', 'full-zip fleece'], 35, 35, 1.15),
  ('base-layer-top', 'tops', 'Base Layer Top', 'Base Layer Top', array['silk pointelle', 'long-sleeve scoopneck'], 88, 88, 1.1),
  ('overcoat', 'outerwear', 'Overcoat', 'Overcoat', array['overcoats'], 40, 40, 1.2)
on conflict (id) do update set
  mother_category_id = excluded.mother_category_id,
  label = excluded.label,
  display_label = excluded.display_label,
  aliases = excluded.aliases,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  search_boost = excluded.search_boost,
  updated_at = now();

with classified as (
  select
    id,
    case
      when product_title_raw ilike '%robe%' then 'sleepwear'
      when product_title_raw ilike '%skort%' then 'bottoms'
      when product_title_raw ilike '%playsuit%' then 'jumpsuits-rompers'
      when product_title_raw ilike '%overcoat%' then 'outerwear'
      when product_title_raw ilike '%fleece%' and product_title_raw ilike '%full%zip%' then 'outerwear'
      when product_title_raw ilike '%tights%' then 'bottoms'
      when product_title_raw ilike '%pullover%' then 'tops'
      when product_title_raw ilike '%henley%' then 'tops'
      when product_title_raw ilike '%pointelle%' or product_title_raw ilike '%scoopneck%' then 'tops'
      else mother_category_id
    end as mother_category_id,
    case
      when product_title_raw ilike '%robe%' then 'robe'
      when product_title_raw ilike '%skort%' then 'skort'
      when product_title_raw ilike '%playsuit%' then 'playsuit'
      when product_title_raw ilike '%overcoat%' then 'overcoat'
      when product_title_raw ilike '%fleece%' and product_title_raw ilike '%full%zip%' then 'fleece'
      when product_title_raw ilike '%tights%' then 'leggings'
      when product_title_raw ilike '%pullover%' then 'pullover'
      when product_title_raw ilike '%henley%' then 'henley'
      when product_title_raw ilike '%pointelle%' or product_title_raw ilike '%scoopneck%' then 'base-layer-top'
      else product_category_raw
    end as product_category_raw,
    case
      when product_title_raw ilike '%robe%' then 'product title: robe'
      when product_title_raw ilike '%skort%' then 'product title: skort'
      when product_title_raw ilike '%playsuit%' then 'product title: playsuit'
      when product_title_raw ilike '%overcoat%' then 'product title: overcoat'
      when product_title_raw ilike '%fleece%' and product_title_raw ilike '%full%zip%' then 'product title: full-zip fleece'
      when product_title_raw ilike '%tights%' then 'product title: tights'
      when product_title_raw ilike '%pullover%' then 'product title: pullover'
      when product_title_raw ilike '%henley%' then 'product title: henley'
      when product_title_raw ilike '%pointelle%' or product_title_raw ilike '%scoopneck%' then 'product title: base layer top'
      else category_evidence
    end as category_evidence
  from staging.product_pages
  where mother_category_id is null or product_category_raw is null
)
update staging.product_pages pp
set
  mother_category_id = classified.mother_category_id,
  product_category_raw = classified.product_category_raw,
  category_evidence = classified.category_evidence,
  category_confidence = case
    when classified.mother_category_id is not null then 'medium'
    else pp.category_confidence
  end,
  needs_manual_review = classified.mother_category_id is null,
  updated_at = now()
from classified
where pp.id = classified.id;

update staging.product_pages
set
  product_title_raw = null,
  product_category_raw = coalesce(product_category_raw, 'archived_product_page_needs_review'),
  category_evidence = 'product page returned unavailable placeholder; needs source review',
  needs_manual_review = true,
  updated_at = now()
where product_title_raw = 'L.L.Bean: Page Not Available';
