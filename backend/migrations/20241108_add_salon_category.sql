ALTER TABLE salons
    ADD COLUMN IF NOT EXISTS category TEXT;

CREATE INDEX IF NOT EXISTS idx_salons_category ON salons(category);
