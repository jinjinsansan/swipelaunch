-- Create tables for salon events and attendees

CREATE TABLE IF NOT EXISTS salon_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    organizer_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ,
    location TEXT,
    meeting_url TEXT,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    capacity INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_salon_events_salon ON salon_events(salon_id);
CREATE INDEX IF NOT EXISTS idx_salon_events_start ON salon_events(start_at);

DROP TRIGGER IF EXISTS trg_salon_events_updated_at ON salon_events;
CREATE TRIGGER trg_salon_events_updated_at
BEFORE UPDATE ON salon_events
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();


CREATE TABLE IF NOT EXISTS salon_event_attendees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES salon_events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'GOING',
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_salon_event_attendees_event ON salon_event_attendees(event_id);
CREATE INDEX IF NOT EXISTS idx_salon_event_attendees_user ON salon_event_attendees(user_id);

DROP TRIGGER IF EXISTS trg_salon_event_attendees_updated_at ON salon_event_attendees;
CREATE TRIGGER trg_salon_event_attendees_updated_at
BEFORE UPDATE ON salon_event_attendees
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();


ALTER TABLE salon_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE salon_event_attendees ENABLE ROW LEVEL SECURITY;
