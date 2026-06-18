insert into public.clothing_types (id, label, sort_order)
values
  ('bikini', 'Bikini', 410),
  ('swimsuit', 'Swimsuit', 420),
  ('bra', 'Bra', 430),
  ('bodysuit', 'Bodysuit', 440),
  ('underwear', 'Underwear', 450),
  ('shorts', 'Shorts', 460),
  ('blazer', 'Blazer', 470),
  ('cardigan', 'Cardigan', 480),
  ('coat', 'Coat', 490),
  ('jacket', 'Jacket', 500),
  ('outerwear', 'Outerwear', 510)
on conflict (id) do update
set
  label = excluded.label,
  sort_order = excluded.sort_order;
