CREATE TABLE IF NOT EXISTS provider_clicks (
 event_id uuid PRIMARY KEY,
 provider_id bigint NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
 action text NOT NULL CHECK(action IN ('photos','whatsapp')),
 visitor_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
