-- Add visibility flags for public metric display
ALTER TABLE salons
    ADD COLUMN IF NOT EXISTS show_member_count_public BOOLEAN DEFAULT TRUE;

ALTER TABLE landing_pages
    ADD COLUMN IF NOT EXISTS show_total_views_public BOOLEAN DEFAULT TRUE;

UPDATE salons
SET show_member_count_public = TRUE
WHERE show_member_count_public IS NULL;

UPDATE landing_pages
SET show_total_views_public = TRUE
WHERE show_total_views_public IS NULL;
