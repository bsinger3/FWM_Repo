-- Dev-only image refresh schema.
-- Do not move this file to supabase/migrations without a separate production
-- promotion plan, rollback plan, and production approval.

do $$
begin
  if to_regclass('public.images') is null then
    raise exception 'public.images is required before applying the dev image refresh migration';
  end if;

  if to_regclass('staging.product_pages') is null then
    raise exception 'staging.product_pages is required; this dev migration has a cross-schema dependency on staging.product_pages(id)';
  end if;
end;
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $function$
begin
  new.updated_at = now();
  return new;
end;
$function$;

create table if not exists public.reviews (
  id uuid primary key default gen_random_uuid(),
  product_page_id uuid not null references staging.product_pages(id),
  normalized_product_page_url text not null,
  source_site text,
  source_review_id text,
  review_identity_key text not null unique,
  reviewer_name_raw text,
  review_date_raw text,
  review_date_parsed date,
  user_comment text,
  source_file text,
  source_row_number text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.reviews is
  'DEV ONLY for the images table refresh. Review ID means one customer review on one product; production promotion requires a separate migration.';

create index if not exists reviews_product_page_id_idx
  on public.reviews (product_page_id);

create index if not exists reviews_normalized_product_page_url_idx
  on public.reviews (normalized_product_page_url);

drop trigger if exists set_reviews_updated_at on public.reviews;
create trigger set_reviews_updated_at
before update on public.reviews
for each row execute function public.set_updated_at();

alter table public.images
  add column if not exists review_id uuid,
  add column if not exists product_page_id uuid,
  add column if not exists review_row_key text,
  add column if not exists source_file text,
  add column if not exists source_row_number text,
  add column if not exists crop_spec jsonb,
  add column if not exists full_body_visible boolean,
  add column if not exists weeks_pregnant integer,
  add column if not exists pregnancy_evidence text,
  add column if not exists prettiness_score double precision,
  add column if not exists prettiness_model_version text,
  add column if not exists prettiness_components jsonb,
  add column if not exists prettiness_scored_at timestamptz;

comment on column public.images.product_page_id is
  'DEV ONLY cross-schema reference to staging.product_pages(id) for the image refresh pass; not portable unless staging schema exists.';

comment on column public.images.crop_spec is
  'Nullable initial crop contract. Manual values use object-position fields; null falls back to existing object-fit cover behavior.';

comment on column public.images.prettiness_score is
  'Internal nullable photo quality / merchandising usefulness score. Not a body, face, age, race, gender, or attractiveness rating.';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'images_review_id_fkey'
      and conrelid = 'public.images'::regclass
  ) then
    alter table public.images
      add constraint images_review_id_fkey
      foreign key (review_id) references public.reviews(id);
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'images_product_page_id_fkey'
      and conrelid = 'public.images'::regclass
  ) then
    alter table public.images
      add constraint images_product_page_id_fkey
      foreign key (product_page_id) references staging.product_pages(id);
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'images'
      and column_name = 'updated_at'
  ) then
    drop trigger if exists set_images_updated_at on public.images;
    create trigger set_images_updated_at
    before update on public.images
    for each row execute function public.set_updated_at();
  end if;
end;
$$;

create index if not exists images_review_id_idx
  on public.images (review_id);

create index if not exists images_product_page_id_idx
  on public.images (product_page_id);

create index if not exists images_review_row_key_idx
  on public.images (review_row_key);

create unique index if not exists images_review_row_key_unique_idx
  on public.images (review_row_key)
  where review_row_key is not null;

create index if not exists images_prettiness_score_idx
  on public.images (prettiness_score)
  where prettiness_score is not null;

grant select, insert, update, delete on public.reviews to service_role;
