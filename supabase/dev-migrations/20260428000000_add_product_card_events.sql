-- Track product-card impressions and clicks for site-side CTR reporting.

CREATE TYPE product_card_event_type AS ENUM (
  'impression',
  'click'
);

CREATE TABLE product_card_events (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type          product_card_event_type NOT NULL,
  image_id            uuid REFERENCES images(id) ON DELETE SET NULL,
  search_event_id     uuid REFERENCES search_events(id) ON DELETE SET NULL,
  anon_id             text NOT NULL,
  session_id          text NOT NULL,
  page_url            text,
  product_url         text,
  source_site_display text,
  card_position       integer,
  result_context      text NOT NULL DEFAULT 'random',
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_product_card_events_event_type ON product_card_events(event_type);
CREATE INDEX idx_product_card_events_image_id ON product_card_events(image_id);
CREATE INDEX idx_product_card_events_search_event_id ON product_card_events(search_event_id);
CREATE INDEX idx_product_card_events_created_at ON product_card_events(created_at);

ALTER TABLE product_card_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can insert product card events"
  ON product_card_events
  FOR INSERT
  WITH CHECK (true);

CREATE POLICY "Service role can read product card events"
  ON product_card_events
  FOR SELECT
  USING (auth.role() = 'service_role');

CREATE VIEW product_card_ctr_daily AS
SELECT
  date_trunc('day', created_at)::date AS event_date,
  count(*) FILTER (WHERE event_type = 'impression') AS impressions,
  count(*) FILTER (WHERE event_type = 'click') AS clicks,
  CASE
    WHEN count(*) FILTER (WHERE event_type = 'impression') = 0 THEN 0
    ELSE (
      count(*) FILTER (WHERE event_type = 'click')::numeric /
      count(*) FILTER (WHERE event_type = 'impression')
    )
  END AS click_through_rate
FROM product_card_events
GROUP BY 1
ORDER BY 1 DESC;
