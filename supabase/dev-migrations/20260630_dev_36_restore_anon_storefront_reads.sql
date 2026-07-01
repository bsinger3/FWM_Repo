-- Restore anon READ access to the storefront-facing tables.
--
-- RLS was enabled on images / clothing_types / clothing_mother_categories WITHOUT
-- an anon SELECT policy, so PostgREST returned 0 rows to the anon frontend — the
-- live homepage's random-results query reads public.images directly and silently
-- got an empty array (200, []). This mirrors the policy production
-- (kmomndloorvrjzmiexxl) has always had on images/clothing_types:
--   SELECT to anon, authenticated USING (true).
--
-- Required for the gosqg -> production cutover: the storefront must be able to
-- read the catalog as the anon role. Idempotent (drop-if-exists before create).
--
-- NOTE for Codex: if you locked these down deliberately, DON'T just re-enable RLS
-- without an anon read policy — the public storefront needs anon SELECT here.

grant select on public.images to anon, authenticated;
drop policy if exists "anon can read images" on public.images;
create policy "anon can read images" on public.images
  for select to anon, authenticated using (true);

grant select on public.clothing_types to anon, authenticated;
drop policy if exists "anon can read clothing_types" on public.clothing_types;
create policy "anon can read clothing_types" on public.clothing_types
  for select to anon, authenticated using (true);

grant select on public.clothing_mother_categories to anon, authenticated;
drop policy if exists "anon can read clothing_mother_categories" on public.clothing_mother_categories;
create policy "anon can read clothing_mother_categories" on public.clothing_mother_categories
  for select to anon, authenticated using (true);
