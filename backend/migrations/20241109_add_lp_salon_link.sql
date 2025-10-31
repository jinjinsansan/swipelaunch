-- Add salon linkage to landing_pages for salon CTA integration

ALTER TABLE landing_pages
    ADD COLUMN IF NOT EXISTS salon_id UUID REFERENCES salons(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_landing_pages_salon ON landing_pages(salon_id);
