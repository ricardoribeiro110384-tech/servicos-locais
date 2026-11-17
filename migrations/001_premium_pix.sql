-- Production and sandbox payments must use separate databases.
ALTER TABLE providers ADD COLUMN IF NOT EXISTS premium_until timestamptz;

CREATE TABLE IF NOT EXISTS premium_pix_payments (
    reference uuid PRIMARY KEY,
    provider_id bigint NOT NULL REFERENCES providers(id),
    mercado_pago_payment_id bigint UNIQUE,
    amount_cents integer NOT NULL CHECK (amount_cents = 1990),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'cancelled', 'refunded')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at timestamptz
);

CREATE INDEX IF NOT EXISTS premium_pix_provider_idx
    ON premium_pix_payments (provider_id, created_at DESC);

-- Run only after server-side verification of the approved Pix at Mercado Pago.
-- Claim the payment once and lock the provider through UPDATE so simultaneous
-- renewals each add their full term.
CREATE OR REPLACE FUNCTION grant_premium_pix(
    payment_reference uuid, remote_payment_id bigint, approved_time timestamptz
) RETURNS timestamptz LANGUAGE sql AS $$
    WITH claimed AS (
        UPDATE premium_pix_payments
        SET status = 'approved', approved_at = approved_time,
            mercado_pago_payment_id = remote_payment_id
        WHERE reference = payment_reference AND status = 'pending'
            AND approved_time IS NOT NULL AND remote_payment_id > 0
            AND (mercado_pago_payment_id IS NULL OR mercado_pago_payment_id = remote_payment_id)
        RETURNING provider_id
    ), extended AS (
        UPDATE providers
        SET premium_until = GREATEST(premium_until, approved_time) + INTERVAL '720 hours'
        FROM claimed
        WHERE providers.id = claimed.provider_id
        RETURNING premium_until
    )
    SELECT premium_until FROM extended;
$$;
