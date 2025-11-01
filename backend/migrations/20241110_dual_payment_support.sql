-- Dual payment support: introduce JPY pricing and payment order tracking

-- 1. Products: add yen pricing metadata
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS price_jpy INTEGER,
    ADD COLUMN IF NOT EXISTS allow_point_purchase BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS allow_jpy_purchase BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5,2) DEFAULT 10.0,
    ADD COLUMN IF NOT EXISTS tax_inclusive BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE products SET allow_point_purchase = TRUE WHERE allow_point_purchase IS NULL;
UPDATE products SET allow_jpy_purchase = FALSE WHERE allow_jpy_purchase IS NULL;

-- 2. Notes: add yen pricing metadata
ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS price_jpy INTEGER,
    ADD COLUMN IF NOT EXISTS allow_point_purchase BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS allow_jpy_purchase BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5,2) DEFAULT 10.0,
    ADD COLUMN IF NOT EXISTS tax_inclusive BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE notes SET allow_point_purchase = TRUE WHERE allow_point_purchase IS NULL;
UPDATE notes SET allow_jpy_purchase = FALSE WHERE allow_jpy_purchase IS NULL;

-- 3. Salons: add yen subscription metadata
ALTER TABLE salons
    ADD COLUMN IF NOT EXISTS monthly_price_jpy INTEGER,
    ADD COLUMN IF NOT EXISTS allow_point_subscription BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS allow_jpy_subscription BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5,2) DEFAULT 10.0,
    ADD COLUMN IF NOT EXISTS tax_inclusive BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE salons SET allow_point_subscription = TRUE WHERE allow_point_subscription IS NULL;
UPDATE salons SET allow_jpy_subscription = FALSE WHERE allow_jpy_subscription IS NULL;

-- 4. Payment orders table: common ledger for yen-based checkouts
CREATE TABLE IF NOT EXISTS payment_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    seller_id UUID REFERENCES users(id) ON DELETE SET NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('product', 'note', 'salon')),
    item_id UUID NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('points', 'yen')),
    currency TEXT NOT NULL DEFAULT 'JPY',
    amount_jpy INTEGER NOT NULL,
    tax_amount_jpy INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'PENDING',
    external_id TEXT UNIQUE,
    checkout_preference_id TEXT,
    payment_order_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payment_orders_user ON payment_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_orders_seller ON payment_orders(seller_id);
CREATE INDEX IF NOT EXISTS idx_payment_orders_item ON payment_orders(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_payment_orders_status ON payment_orders(status);
CREATE INDEX IF NOT EXISTS idx_payment_orders_external ON payment_orders(external_id);

-- 5. Trigger to maintain updated_at timestamp
CREATE OR REPLACE FUNCTION set_payment_order_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_payment_orders_updated_at ON payment_orders;
CREATE TRIGGER trg_payment_orders_updated_at
BEFORE UPDATE ON payment_orders
FOR EACH ROW
EXECUTE PROCEDURE set_payment_order_updated_at();
