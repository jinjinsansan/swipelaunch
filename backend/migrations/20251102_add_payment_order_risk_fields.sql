-- Add risk assessment and dispute tracking fields to payment_orders

ALTER TABLE payment_orders
    ADD COLUMN IF NOT EXISTS risk_score INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS risk_level TEXT NOT NULL DEFAULT 'low',
    ADD COLUMN IF NOT EXISTS risk_factors JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS clearing_state TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS chargeback_hold_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ready_for_payout_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS dispute_flag BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS dispute_reason TEXT,
    ADD COLUMN IF NOT EXISTS dispute_status TEXT,
    ADD COLUMN IF NOT EXISTS dispute_opened_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS dispute_resolved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reserve_amount_usd NUMERIC(18,6) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reserve_released_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS risk_reviewed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS risk_reviewer_id UUID REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE payment_orders
    DROP CONSTRAINT IF EXISTS payment_orders_clearing_state_check;

ALTER TABLE payment_orders
    ADD CONSTRAINT payment_orders_clearing_state_check
    CHECK (clearing_state IN ('pending', 'clearing', 'ready', 'dispute', 'released', 'cancelled'));

CREATE INDEX IF NOT EXISTS idx_payment_orders_ready_for_payout
    ON payment_orders(ready_for_payout_at);

CREATE INDEX IF NOT EXISTS idx_payment_orders_clearing_state
    ON payment_orders(clearing_state, chargeback_hold_until);

CREATE INDEX IF NOT EXISTS idx_payment_orders_dispute
    ON payment_orders(dispute_flag)
    WHERE dispute_flag = TRUE;
