CREATE TABLE IF NOT EXISTS billing_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    full_name TEXT,
    email TEXT,
    phone_number TEXT,
    postal_code TEXT,
    prefecture TEXT,
    city TEXT,
    address_line1 TEXT,
    address_line2 TEXT,
    company_name TEXT,
    country_code TEXT DEFAULT 'JP',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_profiles_email ON billing_profiles(email);

CREATE OR REPLACE FUNCTION trg_billing_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_billing_profiles_updated_at ON billing_profiles;
CREATE TRIGGER trg_billing_profiles_updated_at
BEFORE UPDATE ON billing_profiles
FOR EACH ROW
EXECUTE PROCEDURE trg_billing_profiles_updated_at();
