-- Dev-only: drop the stale legacy match_by_measurements overload.
--
-- The dev DB still carried an older 13-argument overload of
-- match_by_measurements (no in_cup_size parameter) alongside the current
-- 14-argument version. With both present, PostgREST cannot disambiguate a
-- partial named-argument call and fails with PGRST203 ("Could not choose the
-- best candidate function"). The full-param frontend call still resolves to the
-- 14-arg version, but the ambiguity is fragile and the legacy overload also
-- still filters on the deprecated images.clothing_type_id and does not return
-- mother_category_id, so it would return wrong/incomplete results if ever hit.
--
-- The frontend only falls back to the no-cup-size signature when the cup-size
-- version is absent (supportsCupSizeSearchRpc), which never happens here, so
-- dropping the legacy overload is safe.

drop function if exists public.match_by_measurements(
  text, numeric, numeric, numeric, numeric, numeric, boolean, boolean,
  boolean, boolean, boolean, integer, integer
);
