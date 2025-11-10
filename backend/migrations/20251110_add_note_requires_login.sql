-- Add requires_login flag for public notes
ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS requires_login BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS notes_requires_login_idx
    ON notes (requires_login) WHERE visibility = 'public';
