-- Create table for salon announcements

CREATE TABLE IF NOT EXISTS salon_announcements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_salon_announcements_salon ON salon_announcements(salon_id);
CREATE INDEX IF NOT EXISTS idx_salon_announcements_pinned ON salon_announcements(is_pinned);

DROP TRIGGER IF EXISTS trg_salon_announcements_updated_at ON salon_announcements;
CREATE TRIGGER trg_salon_announcements_updated_at
BEFORE UPDATE ON salon_announcements
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();

ALTER TABLE salon_announcements ENABLE ROW LEVEL SECURITY;
