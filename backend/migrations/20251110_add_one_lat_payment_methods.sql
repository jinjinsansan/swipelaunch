-- Create table to store OneLat saved payment methods per user
CREATE TABLE IF NOT EXISTS one_lat_payment_methods (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    one_lat_customer_id TEXT NOT NULL,
    payment_method_id TEXT NOT NULL,
    brand TEXT,
    last4 TEXT,
    exp_month SMALLINT,
    exp_year SMALLINT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, payment_method_id)
);

CREATE INDEX IF NOT EXISTS idx_one_lat_payment_methods_user_id
    ON one_lat_payment_methods(user_id)
    WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION trg_one_lat_payment_methods_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_one_lat_payment_methods_updated_at ON one_lat_payment_methods;
CREATE TRIGGER set_one_lat_payment_methods_updated_at
BEFORE UPDATE ON one_lat_payment_methods
FOR EACH ROW
EXECUTE PROCEDURE trg_one_lat_payment_methods_updated_at();

-- Ensure a single default payment method per user
CREATE OR REPLACE FUNCTION enforce_single_default_one_lat_payment_method()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_default THEN
        UPDATE one_lat_payment_methods
        SET is_default = FALSE, updated_at = NOW()
        WHERE user_id = NEW.user_id AND id <> NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_default_one_lat_payment_methods ON one_lat_payment_methods;
CREATE TRIGGER enforce_default_one_lat_payment_methods
AFTER INSERT OR UPDATE OF is_default ON one_lat_payment_methods
FOR EACH ROW
EXECUTE PROCEDURE enforce_single_default_one_lat_payment_method();

-- Link payment orders with stored payment methods
ALTER TABLE payment_orders
    ADD COLUMN IF NOT EXISTS payment_method_record_id UUID REFERENCES one_lat_payment_methods(id);

CREATE INDEX IF NOT EXISTS idx_payment_orders_payment_method_record_id
    ON payment_orders(payment_method_record_id);

ALTER TABLE one_lat_transactions
    ADD COLUMN IF NOT EXISTS payment_method_record_id UUID REFERENCES one_lat_payment_methods(id);
