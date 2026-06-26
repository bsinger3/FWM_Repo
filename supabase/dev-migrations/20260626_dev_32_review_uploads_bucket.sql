-- Dev-only: STORAGE bucket for user-submitted review photos.
--
-- Creates the 'review-uploads' bucket and the storage.objects RLS policies that
-- let the anon role upload (but not overwrite/delete/list) and let anyone read.
--
-- Bucket is PUBLIC so approved photos can be served straight from the CDN with
-- no signed-URL round-trip. Tradeoff: an object is fetchable by anyone who knows
-- its exact path the moment it's uploaded — i.e. BEFORE moderation. We accept
-- this because (a) paths are unguessable random UUIDs, (b) anon has no LIST
-- permission so the bucket can't be enumerated, and (c) an un-approved photo is
-- never surfaced anywhere on the site (search only shows promoted images rows).
-- If that ever feels too loose, flip the bucket private and switch the client to
-- signed-upload + signed-download; the table/promotion design doesn't change.
--
-- file_size_limit is a 2 MB server-side backstop; the client downscales every
-- photo to a few hundred KB before upload, so this only catches abuse.
--
-- Idempotent: ON CONFLICT for the bucket, DROP POLICY IF EXISTS before CREATE.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'review-uploads',
  'review-uploads',
  true,
  2097152,                                    -- 2 MB
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update set
  public            = excluded.public,
  file_size_limit   = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Anon/authenticated may INSERT (upload) into this bucket only. No UPDATE/DELETE
-- grant, so a user can't overwrite or remove anyone's photo (including their own).
drop policy if exists "anon can upload review photos" on storage.objects;
create policy "anon can upload review photos"
  on storage.objects
  for insert
  to anon, authenticated
  with check (bucket_id = 'review-uploads');

-- Anyone may read objects in this bucket (it's public anyway; this also covers
-- the supabase-js download path).
drop policy if exists "anyone can read review photos" on storage.objects;
create policy "anyone can read review photos"
  on storage.objects
  for select
  to anon, authenticated
  using (bucket_id = 'review-uploads');
