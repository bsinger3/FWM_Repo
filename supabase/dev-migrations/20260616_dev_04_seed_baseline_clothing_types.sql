insert into public.clothing_types (id, label, sort_order)
values
  ('dress', 'Dress', 10),
  ('gown', 'Gown', 20),
  ('jumpsuit', 'Jumpsuit', 30),
  ('romper', 'Romper', 40),
  ('overalls', 'Overalls', 50),
  ('top', 'Top', 100),
  ('shirt', 'Shirt', 110),
  ('blouse', 'Blouse', 120),
  ('tshirt', 'T-Shirt', 130),
  ('tank', 'Tank', 140),
  ('cami', 'Cami', 150),
  ('sweater', 'Sweater', 160),
  ('tunic', 'Tunic', 170),
  ('vest', 'Vest', 180),
  ('bralette', 'Bralette', 190),
  ('bustier', 'Bustier', 200),
  ('skirt', 'Skirt', 300),
  ('pants', 'Pants', 310),
  ('jeans', 'Jeans', 320),
  ('leggings', 'Leggings', 330),
  ('culottes', 'Culottes', 340),
  ('other', 'Other', 999)
on conflict (id) do update
set
  label = excluded.label,
  sort_order = excluded.sort_order;
