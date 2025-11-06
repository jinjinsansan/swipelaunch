ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('public', 'limited', 'private')),
    ADD COLUMN IF NOT EXISTS share_token TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS share_token_rotated_at TIMESTAMPTZ;

UPDATE notes
SET visibility = CASE WHEN status = 'published' THEN 'public' ELSE 'private' END
WHERE visibility IS NULL OR visibility NOT IN ('public', 'limited', 'private');

CREATE INDEX IF NOT EXISTS idx_notes_visibility_status
    ON notes(visibility, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_share_token
    ON notes(share_token)
    WHERE share_token IS NOT NULL;
