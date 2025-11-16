ALTER TABLE landing_pages
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('public', 'limited', 'private')),
    ADD COLUMN IF NOT EXISTS share_token TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS share_token_rotated_at TIMESTAMPTZ;

UPDATE landing_pages
SET visibility = CASE WHEN status = 'published' THEN 'public' ELSE 'private' END
WHERE visibility IS NULL OR visibility NOT IN ('public', 'limited', 'private');

CREATE INDEX IF NOT EXISTS idx_landing_pages_visibility_status
    ON landing_pages(visibility, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_pages_share_token
    ON landing_pages(share_token)
    WHERE share_token IS NOT NULL;
