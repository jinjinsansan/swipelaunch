ALTER TABLE operator_messages
    ADD COLUMN IF NOT EXISTS send_email BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS email_subject TEXT,
    ADD COLUMN IF NOT EXISTS email_from_name TEXT,
    ADD COLUMN IF NOT EXISTS email_from_address TEXT,
    ADD COLUMN IF NOT EXISTS email_reply_to TEXT;

UPDATE operator_messages
SET email_subject = COALESCE(email_subject, title)
WHERE email_subject IS NULL;
