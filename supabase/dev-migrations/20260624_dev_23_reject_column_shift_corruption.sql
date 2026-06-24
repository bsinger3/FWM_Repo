-- Guard against the column-shift corruption that, via a 2026-06-16 off-by-one
-- dev seed, put source-CSV paths into user_comment and row-numbers into
-- source_file (dropping the real review text) on ~9,693 public.images rows.
--
-- A BEFORE INSERT OR UPDATE trigger on public.images and public.reviews rejects
-- any write whose user_comment looks like a file path, or that SETS a purely
-- numeric source_file. The source_file check uses IS DISTINCT FROM OLD so the
-- legacy rows that still carry a numeric source_file (provenance only) can still
-- be updated (e.g. measurement backfills) as long as source_file is unchanged.
--
-- Idempotent: safe to re-run.

create or replace function public.reject_column_shift_corruption()
returns trigger
language plpgsql
as $$
begin
  -- user_comment must never be a file path. The seed always wrote an absolute
  -- /Users/... path ending in .csv; the second clause also catches any other
  -- "<dir>/<file>.csv" shape. Real review text never matches either.
  if new.user_comment is not null
     and (new.user_comment like '/Users/%'
          or (new.user_comment like '%/%' and new.user_comment like '%.csv')) then
    raise exception
      'reject_column_shift_corruption: user_comment looks like a file path '
      '(column-shift corruption) on %.% id=%: %',
      tg_table_schema, tg_table_name, new.id, left(new.user_comment, 100);
  end if;

  -- source_file is a path / file name, never a bare row-number. Only block a
  -- write that *introduces* a numeric source_file, so the existing legacy rows
  -- (already numeric) stay updatable.
  if new.source_file ~ '^[0-9]+$'
     and (tg_op = 'INSERT' or new.source_file is distinct from old.source_file) then
    raise exception
      'reject_column_shift_corruption: source_file is purely numeric '
      '(column-shift corruption) on %.% id=%: %',
      tg_table_schema, tg_table_name, new.id, new.source_file;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_reject_column_shift on public.images;
create trigger trg_reject_column_shift
  before insert or update on public.images
  for each row execute function public.reject_column_shift_corruption();

drop trigger if exists trg_reject_column_shift on public.reviews;
create trigger trg_reject_column_shift
  before insert or update on public.reviews
  for each row execute function public.reject_column_shift_corruption();
