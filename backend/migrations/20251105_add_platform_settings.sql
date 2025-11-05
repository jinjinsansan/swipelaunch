-- Platform settings table for manual exchange rate and fee configuration
CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES users(id)
);

CREATE OR REPLACE FUNCTION trg_platform_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS platform_settings_updated_at ON platform_settings;
CREATE TRIGGER platform_settings_updated_at
BEFORE UPDATE ON platform_settings
FOR EACH ROW
EXECUTE PROCEDURE trg_platform_settings_updated_at();

INSERT INTO platform_settings (key, value)
VALUES
    ('exchange_rate_usd_jpy', to_jsonb(147.0)),
    ('exchange_rate_spread_jpy', to_jsonb(3.0)),
    ('platform_fee_percent', to_jsonb(10.0))
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    updated_at = NOW();
