-- Migration: add immutable editor type support for notes

BEGIN;

ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS editor_type TEXT;

UPDATE notes
SET editor_type = 'classic'
WHERE editor_type IS NULL;

ALTER TABLE notes
    ALTER COLUMN editor_type SET DEFAULT 'classic';

ALTER TABLE notes
    ALTER COLUMN editor_type SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'notes_editor_type_check'
    ) THEN
        ALTER TABLE notes
            ADD CONSTRAINT notes_editor_type_check
            CHECK (editor_type IN ('classic', 'note'));
    END IF;
END$$;

ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS rich_content JSONB;

COMMIT;
