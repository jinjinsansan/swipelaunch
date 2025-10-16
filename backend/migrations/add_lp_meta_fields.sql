ALTER TABLE landing_pages
  ADD COLUMN IF NOT EXISTS meta_title TEXT,
  ADD COLUMN IF NOT EXISTS meta_description TEXT,
  ADD COLUMN IF NOT EXISTS meta_image_url TEXT,
  ADD COLUMN IF NOT EXISTS meta_site_name TEXT;
