ALTER TABLE operator_messages
    ADD COLUMN IF NOT EXISTS admin_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS admin_archived_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_operator_messages_admin_hidden ON operator_messages(admin_hidden);
CREATE INDEX IF NOT EXISTS idx_operator_messages_admin_archived ON operator_messages(admin_archived_at);
