-- Migration: add categories support to notes

ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS categories TEXT[] NOT NULL DEFAULT ARRAY[]::text[];

CREATE INDEX IF NOT EXISTS idx_notes_categories ON notes USING GIN (categories);
