-- Operator messages (admin broadcasts) schema

CREATE TABLE IF NOT EXISTS operator_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    body_text TEXT,
    body_html TEXT,
    category TEXT NOT NULL DEFAULT 'general',
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'draft',
    send_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operator_messages_status ON operator_messages(status);
CREATE INDEX IF NOT EXISTS idx_operator_messages_send_at ON operator_messages(send_at);


CREATE TABLE IF NOT EXISTS operator_message_recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES operator_messages(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    read_at TIMESTAMPTZ,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    web_notified_at TIMESTAMPTZ,
    email_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (message_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_operator_message_recipients_user ON operator_message_recipients(user_id, delivery_status);
CREATE INDEX IF NOT EXISTS idx_operator_message_recipients_message ON operator_message_recipients(message_id);
CREATE INDEX IF NOT EXISTS idx_operator_message_recipients_read ON operator_message_recipients(user_id) WHERE read_at IS NULL;


CREATE TABLE IF NOT EXISTS operator_message_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES operator_messages(id) ON DELETE CASCADE,
    segment_type TEXT NOT NULL,
    segment_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operator_message_segments_message ON operator_message_segments(message_id);


-- Optional: enable row level security for future fine-grained policies
ALTER TABLE operator_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_message_recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_message_segments ENABLE ROW LEVEL SECURITY;
