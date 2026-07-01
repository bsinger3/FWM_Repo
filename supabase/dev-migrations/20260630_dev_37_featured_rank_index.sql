-- The homepage "featured" query (images where featured_rank is not null, ordered)
-- seq-scans all ~47k images and blows the anon 3s statement timeout (57014).
-- Partial index over the ~100 featured rows makes it instant. Needed for cutover.
create index if not exists idx_images_featured_rank
  on public.images (featured_rank)
  where featured_rank is not null;
