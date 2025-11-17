-- Improve public note lookup performance for high-traffic endpoints
-- Adds composite indexes used by /api/notes/public/{slug} and /api/notes/share/{token}

CREATE INDEX IF NOT EXISTS idx_notes_slug_status
    ON notes (slug, status);

CREATE INDEX IF NOT EXISTS idx_notes_share_token_status
    ON notes (share_token, status);
