-- Add expiry column to note_purchases for share unlock feature
-- Share unlocks expire after 7 days by default

ALTER TABLE note_purchases
ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN note_purchases.expires_at IS 'シェアによるアクセス権の有効期限（通常シェアから7日間）';
