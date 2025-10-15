-- Add LP display settings columns
ALTER TABLE landing_pages
    ADD COLUMN IF NOT EXISTS show_swipe_hint BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS fullscreen_media BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS floating_cta BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill existing rows to ensure no nulls
UPDATE landing_pages
SET
    show_swipe_hint = COALESCE(show_swipe_hint, FALSE),
    fullscreen_media = COALESCE(fullscreen_media, FALSE),
    floating_cta = COALESCE(floating_cta, FALSE);
