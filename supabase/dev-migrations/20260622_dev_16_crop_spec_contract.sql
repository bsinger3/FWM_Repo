-- Dev-only. Documents and locks the public.images.crop_spec JSON contract so the
-- auto-crop backfill and the frontend renderer agree on a single shape.
--
-- DO NOT promote to supabase/migrations/ without a separate production plan.
--
-- crop_spec is nullable. null => the card renders the source image with the
-- existing object-fit: cover fallback. Two non-null shapes are allowed:
--
-- 1. mode = "object-position" (manual dashboard crops + orientation audit):
--      { "mode": "object-position", "aspectRatio": "3:4",
--        "objectPositionXPct": 0..100, "objectPositionYPct": 0..100,
--        "zoom": 1..1.6, "rotationDeg": 0|90|180|270, "source": "..." }
--
-- 2. mode = "cover-window" (auto-crop solver, scripts/lib/card-crop-geometry.mjs):
--      explicit crop rectangle as percentages of the SOURCE image —
--      { "mode": "cover-window", "aspectRatio": "3:4",
--        "windowXPct": left edge,  "windowYPct": top edge,
--        "windowWPct": width,      "windowHPct": height,   -- all % of image w/h
--        "rotationDeg": 0|90|180|270, "source": "auto",
--        "cropModelVersion": "...", "scoredAt": "<iso8601>" }   -- provenance (optional)
--
-- The frontend renders cover-window by sizing the image so the window fills the
-- 3:4 card frame and offsetting to the window's top-left (see index.dev.html
-- applyCropSpec). windowWPct/windowHPct are the authoritative crop coordinates;
-- objectPosition/zoom are not used for cover-window.

comment on column public.images.crop_spec is
  'Nullable crop contract. null => object-fit cover fallback. mode "object-position" => manual/orientation crops (objectPositionXPct/YPct, zoom, rotationDeg). mode "cover-window" => auto-crop solver: explicit crop rectangle windowXPct/YPct/WPct/HPct as percent of the source image (authoritative), plus rotationDeg and provenance (source, cropModelVersion, scoredAt). See supabase/dev-migrations/20260622_dev_16_crop_spec_contract.sql.';

-- Lock the shape for new/updated rows. NOT VALID so existing rows are not
-- rescanned (all current rows are null or mode "object-position", which pass).
do $$
begin
  if exists (
    select 1 from pg_constraint where conname = 'images_crop_spec_contract_chk'
  ) then
    alter table public.images drop constraint images_crop_spec_contract_chk;
  end if;

  alter table public.images
    add constraint images_crop_spec_contract_chk check (
      crop_spec is null
      or (
        jsonb_typeof(crop_spec) = 'object'
        and coalesce(crop_spec->>'mode', 'object-position') in ('object-position', 'cover-window')
        and (
          coalesce(crop_spec->>'mode', 'object-position') <> 'cover-window'
          or (
            (crop_spec->>'windowXPct') ~ '^-?[0-9]+(\.[0-9]+)?$'
            and (crop_spec->>'windowYPct') ~ '^-?[0-9]+(\.[0-9]+)?$'
            and (crop_spec->>'windowWPct') ~ '^[0-9]+(\.[0-9]+)?$'
            and (crop_spec->>'windowHPct') ~ '^[0-9]+(\.[0-9]+)?$'
          )
        )
      )
    ) not valid;
end $$;
