-- Dev-only taxonomy seed expansion for product-page classification.
-- Adds broad buckets and controlled item tags needed by the product-page
-- taxonomy audit without touching production migrations.

insert into staging.clothing_mother_categories
  (id, label, display_label, sort_order, frontend_sort_order, is_frontend_filter)
values
  ('activewear', 'Activewear', 'Activewear', 55, 55, true),
  ('jumpsuit', 'Jumpsuit', 'Jumpsuit', 35, 35, true),
  ('romper', 'Romper', 'Romper', 36, 36, true),
  ('shoes', 'Shoes', 'Shoes', 90, 90, true),
  ('accessories', 'Accessories', 'Accessories', 95, 95, true)
on conflict (id) do update set
  label = excluded.label,
  display_label = excluded.display_label,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  is_frontend_filter = excluded.is_frontend_filter,
  updated_at = now();

insert into staging.clothing_type_tags
  (id, mother_category_id, label, display_label, aliases, sort_order, frontend_sort_order, search_boost)
values
  ('jumpsuit', 'jumpsuit', 'Jumpsuit', 'Jumpsuit', array['jumpsuits', 'jump suit'], 10, 10, 1.4),
  ('romper', 'romper', 'Romper', 'Romper', array['rompers', 'playsuit', 'play suit'], 10, 10, 1.4),
  ('overalls', 'dresses', 'Overalls', 'Overalls', array['overall'], 60, 60, 1.1),
  ('cami', 'tops', 'Cami', 'Cami', array['camisole', 'camisoles'], 65, 65, 1.1),
  ('tunic', 'tops', 'Tunic', 'Tunic', array['tunics'], 80, 80, 1.1),
  ('vest', 'tops', 'Vest', 'Vest', array['vests'], 90, 90, 1.1),
  ('bralette', 'intimates', 'Bralette', 'Bralette', array['bralettes'], 22, 22, 1.2),
  ('bustier', 'intimates', 'Bustier', 'Bustier', array['bustiers', 'corset', 'corsets'], 24, 24, 1.2),
  ('activewear', 'activewear', 'Activewear', 'Activewear', array['workout', 'athletic', 'performance'], 10, 10, 1),
  ('sports-bra', 'activewear', 'Sports Bra', 'Sports Bra', array['sports bra', 'sport bra'], 20, 20, 1.3),
  ('yoga-pants', 'activewear', 'Yoga Pants', 'Yoga Pants', array['yoga pant', 'yoga leggings'], 30, 30, 1.2),
  ('sneakers', 'shoes', 'Sneakers', 'Sneakers', array['sneaker', 'trainers', 'athletic shoes'], 20, 20, 1.1),
  ('boots', 'shoes', 'Boots', 'Boots', array['boot', 'booties'], 30, 30, 1.1),
  ('heels', 'shoes', 'Heels', 'Heels', array['heel', 'pumps'], 40, 40, 1.1),
  ('sandals', 'shoes', 'Sandals', 'Sandals', array['sandal'], 50, 50, 1.1),
  ('bag', 'accessories', 'Bag', 'Bag', array['bags', 'handbag', 'purse', 'tote'], 20, 20, 1.1),
  ('belt', 'accessories', 'Belt', 'Belt', array['belts'], 30, 30, 1.1),
  ('scarf', 'accessories', 'Scarf', 'Scarf', array['scarves'], 40, 40, 1.1)
on conflict (id) do update set
  mother_category_id = excluded.mother_category_id,
  label = excluded.label,
  display_label = excluded.display_label,
  aliases = excluded.aliases,
  sort_order = excluded.sort_order,
  frontend_sort_order = excluded.frontend_sort_order,
  search_boost = excluded.search_boost,
  updated_at = now();

insert into public.clothing_types (id, label, sort_order)
values
  ('activewear', 'Activewear', 520),
  ('sports-bra', 'Sports Bra', 530),
  ('yoga-pants', 'Yoga Pants', 540),
  ('sneakers', 'Sneakers', 600),
  ('boots', 'Boots', 610),
  ('heels', 'Heels', 620),
  ('sandals', 'Sandals', 630),
  ('bag', 'Bag', 700),
  ('belt', 'Belt', 710),
  ('scarf', 'Scarf', 720)
on conflict (id) do update
set
  label = excluded.label,
  sort_order = excluded.sort_order;
