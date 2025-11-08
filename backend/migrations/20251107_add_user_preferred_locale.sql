-- Add preferred_locale to users with default 'ja' and constraint for supported locales
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS preferred_locale TEXT DEFAULT 'ja';

UPDATE users
SET preferred_locale = 'ja'
WHERE preferred_locale IS NULL;

ALTER TABLE users
    ALTER COLUMN preferred_locale SET NOT NULL;

ALTER TABLE users
    ADD CONSTRAINT IF NOT EXISTS users_preferred_locale_check
    CHECK (preferred_locale IN ('ja', 'en'));
