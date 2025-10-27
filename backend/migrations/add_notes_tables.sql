-- Migration: create tables for note posts and purchases

CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    cover_image_url TEXT,
    excerpt TEXT,
    content_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_paid BOOLEAN NOT NULL DEFAULT FALSE,
    price_points INTEGER,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_notes_author_status ON notes(author_id, status);
CREATE INDEX IF NOT EXISTS idx_notes_status_published_at ON notes(status, published_at DESC);

CREATE TABLE IF NOT EXISTS note_purchases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    buyer_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    points_spent INTEGER NOT NULL,
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE UNIQUE INDEX IF NOT EXISTS note_purchases_unique ON note_purchases(note_id, buyer_id);

ALTER TABLE point_transactions
ADD COLUMN IF NOT EXISTS related_note_id UUID REFERENCES notes(id) ON DELETE SET NULL;
