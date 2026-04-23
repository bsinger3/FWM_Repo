-- Migration: add_image_reports
-- Creates a table to store user-submitted reports on image cards.

CREATE TYPE image_report_reason AS ENUM (
  'duplicate_image',
  'incorrect_data',
  'image_not_helpful',
  'dead_link',
  'sold_out',
  'other_link_problem'
);

CREATE TABLE image_reports (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  image_id    uuid NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  reason      image_report_reason NOT NULL,
  anon_id     text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_image_reports_image_id ON image_reports(image_id);
CREATE INDEX idx_image_reports_anon_id ON image_reports(anon_id);

ALTER TABLE image_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can insert a report"
  ON image_reports
  FOR INSERT
  WITH CHECK (true);

CREATE POLICY "Service role can read reports"
  ON image_reports
  FOR SELECT
  USING (auth.role() = 'service_role');
