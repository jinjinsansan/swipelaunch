-- Add LP linkage to salons table for bidirectional salon-LP association

ALTER TABLE salons
    ADD COLUMN IF NOT EXISTS lp_id UUID REFERENCES landing_pages(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_salons_lp ON salons(lp_id);

COMMENT ON COLUMN salons.lp_id IS 'LP that links to this salon (managed from salon edit page)';
