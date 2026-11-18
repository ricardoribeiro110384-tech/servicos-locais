CREATE TABLE IF NOT EXISTS professional_accounts (
 phone text PRIMARY KEY, salt text NOT NULL, password_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS professional_sessions (
 token_hash text PRIMARY KEY, phone text NOT NULL REFERENCES professional_accounts(phone) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '7 days'
);
CREATE TABLE IF NOT EXISTS professional_photos (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 provider_id bigint NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
 image bytea NOT NULL, created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS professional_login_attempts (
 phone text PRIMARY KEY, attempts integer NOT NULL DEFAULT 0,
 window_start timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
