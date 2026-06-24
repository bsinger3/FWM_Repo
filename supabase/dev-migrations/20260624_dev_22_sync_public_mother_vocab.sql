-- Dev-only: sync public.clothing_mother_categories to the authoritative
-- staging.clothing_mother_categories vocabulary.
--
-- dev_20 hand-seeded the public vocab and got it wrong: it used 'jumpsuit'
-- (singular) and 'romper', and was missing 'activewear', 'shoes', and
-- 'accessories'. The real FK vocabulary (staging.clothing_mother_categories,
-- the target of staging.product_pages.mother_category_id) uses 'jumpsuits'
-- (plural), has no 'romper', and includes activewear/shoes/accessories. Mirror
-- staging exactly so the frontend dropdown, the chip labels, and the
-- images.mother_category_id values all share one vocabulary.

insert into public.clothing_mother_categories (id, label, sort_order)
select id, label, coalesce(sort_order, 999)
from staging.clothing_mother_categories
on conflict (id) do update
  set label = excluded.label,
      sort_order = excluded.sort_order;

-- Drop public ids that no longer exist in staging (e.g. the bogus 'jumpsuit'
-- singular and 'romper' from dev_20).
delete from public.clothing_mother_categories p
where not exists (
  select 1 from staging.clothing_mother_categories s where s.id = p.id
);
