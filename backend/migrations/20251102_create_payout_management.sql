-- Comprehensive payout management tables for seller disbursements

-- 1. Seller payout settings (TRC20 wallet, cycle metadata)
CREATE TABLE IF NOT EXISTS payout_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    usdt_address TEXT NOT NULL,
    address_label TEXT,
    preferred_network TEXT NOT NULL DEFAULT 'TRC20',
    payout_cycle_days INTEGER NOT NULL DEFAULT 10,
    address_verified_at TIMESTAMPTZ,
    payout_note TEXT,
    last_reviewed_at TIMESTAMPTZ,
    reviewer_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Payout ledger master (one row per seller payment window)
CREATE TABLE IF NOT EXISTS payout_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seller_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seller_username TEXT,
    seller_email TEXT,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    settlement_due_at TIMESTAMPTZ NOT NULL,
    funds_expected_at TIMESTAMPTZ,
    payout_cycle_days INTEGER NOT NULL DEFAULT 10,
    one_lat_batch_id TEXT,
    currency TEXT NOT NULL DEFAULT 'USDT',
    gross_amount_usd NUMERIC(18,6) NOT NULL DEFAULT 0,
    gross_amount_usdt NUMERIC(18,6),
    gross_amount_points INTEGER,
    fee_amount_usd NUMERIC(18,6) DEFAULT 0,
    fee_amount_usdt NUMERIC(18,6),
    net_amount_usd NUMERIC(18,6),
    net_amount_usdt NUMERIC(18,6),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','funds_received','ready_to_payout','paid','on_hold','cancelled')),
    seller_wallet_snapshot TEXT,
    admin_tx_hash TEXT,
    admin_tx_network TEXT DEFAULT 'TRC20',
    admin_tx_memo TEXT,
    admin_tx_confirmed_at TIMESTAMPTZ,
    notes TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_status_change_at TIMESTAMPTZ,
    last_status_changed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Line items assigned to each payout (source transaction breakdown)
CREATE TABLE IF NOT EXISTS payout_line_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payout_id UUID NOT NULL REFERENCES payout_ledger(id) ON DELETE CASCADE,
    seller_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ,
    buyer_id UUID,
    description TEXT,
    gross_amount_usd NUMERIC(18,6),
    gross_amount_jpy NUMERIC(18,2),
    gross_amount_points INTEGER,
    gross_amount_usdt NUMERIC(18,6),
    fee_amount_usd NUMERIC(18,6),
    fee_amount_usdt NUMERIC(18,6),
    net_amount_usd NUMERIC(18,6),
    net_amount_usdt NUMERIC(18,6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_type, source_id)
);

-- 4. Event log per payout (status changes, operator notes, etc.)
CREATE TABLE IF NOT EXISTS payout_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payout_id UUID NOT NULL REFERENCES payout_ledger(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    title TEXT,
    body TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. Updated_at trigger helper for payout tables
CREATE OR REPLACE FUNCTION set_payout_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_payout_settings_updated_at ON payout_settings;
CREATE TRIGGER trg_payout_settings_updated_at
BEFORE UPDATE ON payout_settings
FOR EACH ROW
EXECUTE PROCEDURE set_payout_updated_at();

DROP TRIGGER IF EXISTS trg_payout_ledger_updated_at ON payout_ledger;
CREATE TRIGGER trg_payout_ledger_updated_at
BEFORE UPDATE ON payout_ledger
FOR EACH ROW
EXECUTE PROCEDURE set_payout_updated_at();

-- 6. Helpful indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_payout_settings_reviewer ON payout_settings(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_payout_ledger_seller ON payout_ledger(seller_id);
CREATE INDEX IF NOT EXISTS idx_payout_ledger_status ON payout_ledger(status, settlement_due_at);
CREATE INDEX IF NOT EXISTS idx_payout_ledger_due_at ON payout_ledger(settlement_due_at);
CREATE INDEX IF NOT EXISTS idx_payout_line_items_seller ON payout_line_items(seller_id);
CREATE INDEX IF NOT EXISTS idx_payout_line_items_payout ON payout_line_items(payout_id);
CREATE INDEX IF NOT EXISTS idx_payout_events_payout ON payout_events(payout_id, created_at DESC);

-- 7. Enable RLS and define access policies (app layer uses service key, but keep least privilege)
ALTER TABLE payout_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE payout_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE payout_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE payout_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY payout_settings_self_manage ON payout_settings
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY payout_ledger_self_select ON payout_ledger
    FOR SELECT
    USING (auth.uid() = seller_id);

CREATE POLICY payout_line_items_self_select ON payout_line_items
    FOR SELECT
    USING (auth.uid() = seller_id);

CREATE POLICY payout_events_self_select ON payout_events
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1
            FROM payout_ledger
            WHERE payout_ledger.id = payout_events.payout_id
              AND payout_ledger.seller_id = auth.uid()
        )
    );
