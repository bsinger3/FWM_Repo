-- Dev-only landing tables for the Reddit post harvester (RSS, file-first → DB).
--
-- Source of records: scripts/harvest-reddit-posts.mjs writes NDJSON to the
-- sibling FWM_Data/reddit_harvest/posts.ndjson. A later promote step will load
-- those rows into staging.reddit_posts. Goal: find posts where people ask for
-- clothing/fit help and include body measurements, then match them to rows in
-- public.images and reply (eventually within 24h) with a pre-filled FWM search.
--
-- DEV ONLY. Lives in supabase/dev-migrations/, never the production path.

create schema if not exists staging;
grant usage on schema staging to postgres;
grant usage on schema staging to service_role;

-- ---------------------------------------------------------------------------
-- staging.reddit_posts — one row per harvested post
-- ---------------------------------------------------------------------------
create table if not exists staging.reddit_posts (
  id uuid primary key default gen_random_uuid(),

  -- provenance / raw content
  reddit_fullname text unique not null,         -- dedup key, e.g. t3_1uc2nw9
  subreddit text not null,
  permalink text,                               -- click-to-visit link to the post
  author_username text,
  post_title text,
  post_body text,                               -- full, untruncated selftext
  post_flair text,
  created_utc timestamptz,                       -- when OP posted (drives the SLA)
  harvested_at timestamptz,                      -- when we pulled it
  source text not null default 'reddit_rss_new',
  raw_record jsonb,                              -- full original NDJSON, for reprocessing

  -- what OP is asking for (clothing-type extraction deferred → lands NULL for now;
  -- requested_clothing_type_id is a soft pointer to the clothing-type taxonomy)
  request_summary text,
  requested_clothing_type_id text,
  requested_clothing_raw text,
  intent text check (intent in ('recommend_request','body_shape_id','fit_check','other')),

  -- extracted measurements (named to mirror public.images columns)
  height_in numeric,                             -- ~ height_in_display
  weight_lbs numeric,                            -- ~ weight_lbs_display
  bust_in numeric,                               -- ~ bust_in_number_display
  waist_in numeric,                              -- ~ waist_in
  hips_in numeric,                               -- ~ hips_in_display
  inseam_in numeric,                             -- ~ inseam_inches_display
  band_size integer,                             -- bra band, e.g. 32
  cup_size text,                                 -- ~ cupsize_display, e.g. 'DD'
  has_measurements boolean not null default false,
  measurements_raw jsonb,                        -- raw matched strings + unparsed, for audit

  -- workflow + reply tracking
  status text not null default 'new'
    check (status in ('new','needs_review','approved','rejected','responded')),
  gender_guess text,
  relevance_tier text check (relevance_tier in ('high','medium','low','manual')),
  response_deadline timestamptz,                 -- created_utc + 24h SLA, set by trigger below
  match_status text not null default 'pending'
    check (match_status in ('pending','matched','no_match')),
  match_query_url text,                          -- pre-filled FWM search link to paste in the reply
  reply_status text not null default 'pending'
    check (reply_status in ('pending','drafted','sent','skipped')),
  reply_permalink text,                          -- URL of our posted comment, once sent
  responded_at timestamptz,
  reviewed_by text,
  reviewed_at timestamptz,
  notes text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table staging.reddit_posts is
  'Harvested Reddit posts (clothing-fit help + body measurements) staged for matching to public.images and replying. Dev-only; not used by the live website.';

create index if not exists reddit_posts_status_idx on staging.reddit_posts (status);
create index if not exists reddit_posts_match_status_idx on staging.reddit_posts (match_status);
create index if not exists reddit_posts_reply_status_idx on staging.reddit_posts (reply_status);
create index if not exists reddit_posts_deadline_idx on staging.reddit_posts (response_deadline);
create index if not exists reddit_posts_has_meas_idx on staging.reddit_posts (has_measurements);
create index if not exists reddit_posts_subreddit_idx on staging.reddit_posts (subreddit);
create index if not exists reddit_posts_created_utc_idx on staging.reddit_posts (created_utc);

-- ---------------------------------------------------------------------------
-- staging.reddit_post_matches — post ↔ catalog image (one post → many cards)
-- image_id is a SOFT reference (no FK): public.images is rebuilt/refreshed by the
-- dev pipeline, so a hard FK would cascade-delete match history on every refresh.
-- ---------------------------------------------------------------------------
create table if not exists staging.reddit_post_matches (
  id uuid primary key default gen_random_uuid(),
  reddit_post_id uuid not null references staging.reddit_posts(id) on delete cascade,
  image_id uuid not null,                        -- → public.images.id (soft ref)
  match_score numeric,                           -- fit quality (measurements + clothing type)
  match_rank integer,                            -- 1 = best, for ordering the reply
  included_in_reply boolean not null default false,
  created_at timestamptz not null default now(),
  unique (reddit_post_id, image_id)
);

comment on table staging.reddit_post_matches is
  'Catalog images (public.images) matched to a harvested Reddit post. image_id is a soft reference (no FK) because public.images is refreshed by the dev pipeline.';

create index if not exists reddit_post_matches_post_idx on staging.reddit_post_matches (reddit_post_id);
create index if not exists reddit_post_matches_image_idx on staging.reddit_post_matches (image_id);

-- reuse the existing updated_at trigger function (defined in dev_00/dev_01)
drop trigger if exists set_reddit_posts_updated_at on staging.reddit_posts;
create trigger set_reddit_posts_updated_at
  before update on staging.reddit_posts
  for each row execute function public.set_updated_at();

-- response_deadline = created_utc + 24h. A generated column can't express this
-- (timestamptz + interval is STABLE, not IMMUTABLE), so populate it via trigger.
create or replace function staging.reddit_set_response_deadline()
returns trigger language plpgsql as $$
begin
  new.response_deadline := new.created_utc + interval '24 hours';
  return new;
end;
$$;

drop trigger if exists set_reddit_posts_deadline on staging.reddit_posts;
create trigger set_reddit_posts_deadline
  before insert or update of created_utc on staging.reddit_posts
  for each row execute function staging.reddit_set_response_deadline();

grant all on staging.reddit_posts to postgres, service_role;
grant all on staging.reddit_post_matches to postgres, service_role;
