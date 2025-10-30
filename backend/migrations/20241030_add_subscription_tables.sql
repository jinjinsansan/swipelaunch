-- Subscription support tables for ONE.lat recurring payments

CREATE TABLE IF NOT EXISTS one_lat_subscription_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_key TEXT NOT NULL,
    subscription_plan_id TEXT NOT NULL,
    points_per_cycle INTEGER NOT NULL,
    usd_amount NUMERIC(10,2) NOT NULL,
    checkout_preference_id TEXT,
    external_id TEXT UNIQUE NOT NULL,
    recurrent_payment_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    seller_id UUID,
    seller_username TEXT,
    success_url TEXT,
    error_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_one_lat_subscription_sessions_user
    ON one_lat_subscription_sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_one_lat_subscription_sessions_external
    ON one_lat_subscription_sessions(external_id);

CREATE INDEX IF NOT EXISTS idx_one_lat_subscription_sessions_recurrent
    ON one_lat_subscription_sessions(recurrent_payment_id);


CREATE TABLE IF NOT EXISTS user_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_key TEXT NOT NULL,
    subscription_plan_id TEXT NOT NULL,
    points_per_cycle INTEGER NOT NULL,
    usd_amount NUMERIC(10,2) NOT NULL,
    checkout_preference_id TEXT,
    external_id TEXT,
    recurrent_payment_id TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    last_event_type TEXT,
    last_event_at TIMESTAMPTZ,
    next_charge_at TIMESTAMPTZ,
    last_charge_at TIMESTAMPTZ,
    seller_id UUID,
    seller_username TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user
    ON user_subscriptions(user_id);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_plan
    ON user_subscriptions(plan_key);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_recurrent
    ON user_subscriptions(recurrent_payment_id);


CREATE TABLE IF NOT EXISTS subscription_charge_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_subscription_id UUID NOT NULL REFERENCES user_subscriptions(id) ON DELETE CASCADE,
    event_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT,
    amount_usd NUMERIC(10,2),
    points_granted INTEGER,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_subscription_charge_history_subscription
    ON subscription_charge_history(user_subscription_id);


CREATE OR REPLACE FUNCTION set_subscription_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_subscription_sessions_updated_at ON one_lat_subscription_sessions;
CREATE TRIGGER trg_subscription_sessions_updated_at
BEFORE UPDATE ON one_lat_subscription_sessions
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();

DROP TRIGGER IF EXISTS trg_user_subscriptions_updated_at ON user_subscriptions;
CREATE TRIGGER trg_user_subscriptions_updated_at
BEFORE UPDATE ON user_subscriptions
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();
