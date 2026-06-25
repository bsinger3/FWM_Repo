-- Dev-only: add real source-resolution columns to public.images.
--
-- Context: public.images already HAS width/height (text) columns, but they are
-- effectively empty (0 usable numeric values across ~47.9k rows) — so source
-- resolution is unknown server-side. That's what makes the pixelation problem
-- (low-res source + garment-aware auto-crop zoom) impossible to gate in the
-- match_by_measurements RPC: the DB can't tell a 600px photo from a 2000px one.
--
-- We do NOT overwrite the legacy text width/height columns — they're import
-- provenance from the scrape. Instead add dedicated numeric columns that the
-- dimension backfill (scripts/backfill-dev-image-dimensions.mjs) populates by
-- reading each image's header bytes:
--   source_width_px / source_height_px  intrinsic pixel dimensions of the source
--   dimensions_checked_at                when we last probed the header
--   dimensions_source                    how we got them ('header_fetch', etc.)
--
-- Idempotent: ADD COLUMN IF NOT EXISTS. Re-running is safe.

alter table public.images
  add column if not exists source_width_px integer,
  add column if not exists source_height_px integer,
  add column if not exists dimensions_checked_at timestamptz,
  add column if not exists dimensions_source text;

comment on column public.images.source_width_px is
  'Intrinsic pixel width of the source image (from header probe). Null = unknown / not yet probed.';
comment on column public.images.source_height_px is
  'Intrinsic pixel height of the source image (from header probe). Null = unknown / not yet probed.';
comment on column public.images.dimensions_checked_at is
  'When source_width_px/source_height_px were last probed.';
comment on column public.images.dimensions_source is
  'How dimensions were obtained, e.g. header_fetch.';
