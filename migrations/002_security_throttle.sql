-- Run in Neon BEFORE deploying the app code that reads this table.
-- The key is a one-way HMAC of the client IP; raw IPs are not saved.
CREATE TABLE IF NOT EXISTS security_throttle (
    throttle_key text PRIMARY KEY,
    window_start bigint NOT NULL,
    attempts integer NOT NULL
);
