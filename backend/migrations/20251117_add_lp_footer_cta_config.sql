-- Add footer CTA configuration to landing pages
ALTER TABLE landing_pages
    ADD COLUMN IF NOT EXISTS footer_cta_config JSONB;

-- Ensure null by default for legacy rows
UPDATE landing_pages
SET footer_cta_config = NULL
WHERE footer_cta_config IS NULL;
