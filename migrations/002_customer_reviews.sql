CREATE TABLE IF NOT EXISTS customer_reviews (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 provider_id bigint NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
 name text NOT NULL CHECK (char_length(name) BETWEEN 2 AND 80),
 stars integer NOT NULL CHECK (stars BETWEEN 1 AND 5),
 comment text NOT NULL DEFAULT '' CHECK (char_length(comment) <= 500),
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
 created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS customer_reviews_pending_idx ON customer_reviews(status, created_at);
