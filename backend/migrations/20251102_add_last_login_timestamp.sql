-- Ensure users table tracks last login timestamp

ALTER TABLE users
ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

COMMENT ON COLUMN users.last_login_at IS 'Most recent login timestamp for the user (UTC).';
