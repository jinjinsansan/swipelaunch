-- Create tables for salon asset library

CREATE TABLE IF NOT EXISTS salon_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    uploader_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL,
    title TEXT,
    description TEXT,
    file_url TEXT NOT NULL,
    thumbnail_url TEXT,
    content_type TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'MEMBERS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_salon_assets_salon ON salon_assets(salon_id);
CREATE INDEX IF NOT EXISTS idx_salon_assets_visibility ON salon_assets(visibility);

DROP TRIGGER IF EXISTS trg_salon_assets_updated_at ON salon_assets;
CREATE TRIGGER trg_salon_assets_updated_at
BEFORE UPDATE ON salon_assets
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();

ALTER TABLE salon_assets ENABLE ROW LEVEL SECURITY;
