-- Dev-only compatibility for product card impression/view/click tracking.
-- Mirrors the existing production migration shape so local dev preview does
-- not throw console errors while exercising the refreshed image table.

do $$
begin
  if not exists (select 1 from pg_type where typname = 'product_card_event_type') then
    create type public.product_card_event_type as enum ('impression', 'click', 'view');
  end if;
end;
$$;

alter type public.product_card_event_type add value if not exists 'impression';
alter type public.product_card_event_type add value if not exists 'click';
alter type public.product_card_event_type add value if not exists 'view';

create table if not exists public.product_card_events (
  id uuid primary key default gen_random_uuid(),
  event_type public.product_card_event_type not null,
  image_id uuid references public.images(id) on delete set null,
  search_event_id uuid references public.search_events(id) on delete set null,
  anon_id text not null,
  session_id text not null,
  page_url text,
  product_url text,
  source_site_display text,
  card_position integer,
  result_context text not null default 'random',
  created_at timestamptz not null default now()
);

create index if not exists idx_product_card_events_event_type
  on public.product_card_events(event_type);

create index if not exists idx_product_card_events_image_id
  on public.product_card_events(image_id);

create index if not exists idx_product_card_events_search_event_id
  on public.product_card_events(search_event_id);

create index if not exists idx_product_card_events_created_at
  on public.product_card_events(created_at);

alter table public.product_card_events enable row level security;

drop policy if exists "Anyone can insert product card events" on public.product_card_events;
create policy "Anyone can insert product card events"
  on public.product_card_events
  for insert
  with check (true);

drop policy if exists "Service role can read product card events" on public.product_card_events;
create policy "Service role can read product card events"
  on public.product_card_events
  for select
  using (auth.role() = 'service_role');

grant insert on public.product_card_events to anon;
grant insert on public.product_card_events to authenticated;
grant select, insert, update, delete on public.product_card_events to service_role;

drop view if exists public.product_card_ctr_daily;
create view public.product_card_ctr_daily as
select
  date_trunc('day', created_at)::date as event_date,
  count(*) filter (where event_type::text = 'impression') as impressions,
  count(*) filter (where event_type::text = 'view') as views,
  count(*) filter (where event_type::text = 'click') as clicks,
  case
    when count(*) filter (where event_type::text = 'impression') = 0 then 0
    else (
      count(*) filter (where event_type::text = 'click')::numeric /
      count(*) filter (where event_type::text = 'impression')
    )
  end as click_through_rate,
  case
    when count(*) filter (where event_type::text = 'view') = 0 then 0
    else (
      count(*) filter (where event_type::text = 'click')::numeric /
      count(*) filter (where event_type::text = 'view')
    )
  end as view_click_through_rate
from public.product_card_events
group by 1
order by 1 desc;

grant select on public.product_card_ctr_daily to service_role;
