-- Extend moderation events for additional entities

ALTER TABLE moderation_events
    ADD COLUMN IF NOT EXISTS target_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS target_salon_id UUID REFERENCES salons(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_moderation_events_salon ON moderation_events(target_salon_id);
CREATE INDEX IF NOT EXISTS idx_moderation_events_note ON moderation_events(target_note_id);
