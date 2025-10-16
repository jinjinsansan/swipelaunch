ALTER TABLE landing_pages
  ADD COLUMN IF NOT EXISTS custom_theme_hex VARCHAR(7),
  ADD COLUMN IF NOT EXISTS custom_theme_shades JSONB;
