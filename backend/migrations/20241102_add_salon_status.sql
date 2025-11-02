-- Add status management columns for salons

ALTER TABLE salons
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'approved'
        CHECK (status IN ('pending', 'approved', 'rejected', 'suspended')),
    ADD COLUMN IF NOT EXISTS moderation_notes TEXT;

UPDATE salons
SET status = 'approved'
WHERE status IS NULL;

CREATE INDEX IF NOT EXISTS idx_salons_status ON salons(status);
