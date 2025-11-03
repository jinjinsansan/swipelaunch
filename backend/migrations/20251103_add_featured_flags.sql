-- Add featured flag columns to marketplace entities

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE salons
    ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill existing rows to explicit false
UPDATE products SET is_featured = COALESCE(is_featured, FALSE);
UPDATE notes SET is_featured = COALESCE(is_featured, FALSE);
UPDATE salons SET is_featured = COALESCE(is_featured, FALSE);
