-- Dev-only image orientation audit traceability fields.
-- The frontend display contract remains public.images.crop_spec.rotationDeg.

do $$
begin
  if to_regclass('public.images') is null then
    raise exception 'public.images is required before applying dev image orientation audit fields';
  end if;
end $$;

alter table public.images
  add column if not exists image_orientation_degrees integer,
  add column if not exists image_orientation_confidence text,
  add column if not exists image_orientation_evidence jsonb,
  add column if not exists image_orientation_checked_at timestamptz,
  add column if not exists image_orientation_model_version text;

comment on column public.images.image_orientation_degrees is
  'DEV ONLY audit mirror of crop_spec.rotationDeg for approved orientation corrections. Allowed values: 0, 90, 180, 270.';

comment on column public.images.image_orientation_evidence is
  'DEV ONLY evidence used by the orientation audit, such as EXIF orientation, dimensions, and detector signals.';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'images_orientation_degrees_check'
      and conrelid = 'public.images'::regclass
  ) then
    alter table public.images
      add constraint images_orientation_degrees_check
      check (image_orientation_degrees is null or image_orientation_degrees in (0, 90, 180, 270));
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'images_orientation_confidence_check'
      and conrelid = 'public.images'::regclass
  ) then
    alter table public.images
      add constraint images_orientation_confidence_check
      check (image_orientation_confidence is null or image_orientation_confidence in ('high', 'medium', 'low'));
  end if;
end $$;

create index if not exists images_orientation_degrees_idx
  on public.images (image_orientation_degrees);

create index if not exists images_orientation_checked_at_idx
  on public.images (image_orientation_checked_at);
