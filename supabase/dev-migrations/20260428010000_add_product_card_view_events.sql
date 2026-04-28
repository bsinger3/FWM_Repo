-- Add visible product-card views in addition to render impressions.

ALTER TYPE product_card_event_type ADD VALUE IF NOT EXISTS 'view';

DROP VIEW IF EXISTS product_card_ctr_daily;

CREATE VIEW product_card_ctr_daily AS
SELECT
  date_trunc('day', created_at)::date AS event_date,
  count(*) FILTER (WHERE event_type::text = 'impression') AS impressions,
  count(*) FILTER (WHERE event_type::text = 'view') AS views,
  count(*) FILTER (WHERE event_type::text = 'click') AS clicks,
  CASE
    WHEN count(*) FILTER (WHERE event_type::text = 'impression') = 0 THEN 0
    ELSE (
      count(*) FILTER (WHERE event_type::text = 'click')::numeric /
      count(*) FILTER (WHERE event_type::text = 'impression')
    )
  END AS click_through_rate,
  CASE
    WHEN count(*) FILTER (WHERE event_type::text = 'view') = 0 THEN 0
    ELSE (
      count(*) FILTER (WHERE event_type::text = 'click')::numeric /
      count(*) FILTER (WHERE event_type::text = 'view')
    )
  END AS view_click_through_rate
FROM product_card_events
GROUP BY 1
ORDER BY 1 DESC;
