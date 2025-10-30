-- Online salon core tables and existing schema extensions

-- 1. Salons
CREATE TABLE IF NOT EXISTS salons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    thumbnail_url TEXT,
    subscription_plan_id TEXT NOT NULL,
    subscription_external_id TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subscription_plan_id)
);

CREATE INDEX IF NOT EXISTS idx_salons_owner ON salons(owner_id);


-- 2. Salon memberships (users belonging to a salon via subscription)
CREATE TABLE IF NOT EXISTS salon_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    recurrent_payment_id TEXT,
    subscription_session_external_id TEXT,
    last_event_type TEXT,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_charged_at TIMESTAMPTZ,
    next_charge_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (salon_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_salon_memberships_salon ON salon_memberships(salon_id);
CREATE INDEX IF NOT EXISTS idx_salon_memberships_user ON salon_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_salon_memberships_status ON salon_memberships(status);


-- 3. Salon products (tie products to salons/subscription plans)
CREATE TABLE IF NOT EXISTS salon_products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    subscription_plan_id TEXT NOT NULL,
    subscription_session_external_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id)
);

CREATE INDEX IF NOT EXISTS idx_salon_products_salon ON salon_products(salon_id);


-- 4. Note free-access mapping for salons
CREATE TABLE IF NOT EXISTS note_salon_access (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    allow_free_access BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (note_id, salon_id)
);

CREATE INDEX IF NOT EXISTS idx_note_salon_access_note ON note_salon_access(note_id);
CREATE INDEX IF NOT EXISTS idx_note_salon_access_salon ON note_salon_access(salon_id);


-- 5. Extend existing tables for salon support
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS product_type TEXT;

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS salon_id UUID REFERENCES salons(id) ON DELETE SET NULL;

UPDATE products
SET product_type = 'points'
WHERE product_type IS NULL;

ALTER TABLE products
    ALTER COLUMN product_type SET NOT NULL;

ALTER TABLE products
    ALTER COLUMN product_type SET DEFAULT 'points';

CREATE INDEX IF NOT EXISTS idx_products_type ON products(product_type);
CREATE INDEX IF NOT EXISTS idx_products_salon ON products(salon_id);


ALTER TABLE one_lat_subscription_sessions
    ADD COLUMN IF NOT EXISTS salon_id UUID REFERENCES salons(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_subscription_sessions_salon
    ON one_lat_subscription_sessions(salon_id);


ALTER TABLE user_subscriptions
    ADD COLUMN IF NOT EXISTS salon_id UUID REFERENCES salons(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_salon
    ON user_subscriptions(salon_id);


ALTER TABLE subscription_charge_history
    ADD COLUMN IF NOT EXISTS salon_id UUID REFERENCES salons(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_subscription_charge_history_salon
    ON subscription_charge_history(salon_id);


-- 6. Updated_at triggers (re-use existing function set_subscription_updated_at)
DROP TRIGGER IF EXISTS trg_salons_updated_at ON salons;
CREATE TRIGGER trg_salons_updated_at
BEFORE UPDATE ON salons
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();

DROP TRIGGER IF EXISTS trg_salon_memberships_updated_at ON salon_memberships;
CREATE TRIGGER trg_salon_memberships_updated_at
BEFORE UPDATE ON salon_memberships
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();

DROP TRIGGER IF EXISTS trg_note_salon_access_updated_at ON note_salon_access;
CREATE TRIGGER trg_note_salon_access_updated_at
BEFORE UPDATE ON note_salon_access
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();


-- 7. Row Level Security (optional, service role bypasses but enable for future policies)
ALTER TABLE salons ENABLE ROW LEVEL SECURITY;
ALTER TABLE salon_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE salon_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_salon_access ENABLE ROW LEVEL SECURITY;
