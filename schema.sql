CREATE TABLE IF NOT EXISTS providers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category text NOT NULL,
    name text NOT NULL,
    phone text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    premium integer NOT NULL DEFAULT 0,
    description text NOT NULL DEFAULT '',
    photo text NOT NULL DEFAULT '',
    reviews text NOT NULL DEFAULT '[]',
    UNIQUE (category, phone)
);

CREATE TABLE IF NOT EXISTS admin_credential (
    id integer PRIMARY KEY CHECK (id = 1),
    recovery_fingerprint text NOT NULL,
    salt text NOT NULL,
    password_hash text NOT NULL
);

-- Shared throttles persist across Vercel serverless instances.
CREATE TABLE IF NOT EXISTS security_throttle (
    throttle_key text PRIMARY KEY,
    window_start bigint NOT NULL,
    attempts integer NOT NULL
);
