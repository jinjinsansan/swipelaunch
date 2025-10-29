-- Migration: Add official share tweet tracking fields for retweet unlock

ALTER TABLE notes
ADD COLUMN IF NOT EXISTS official_share_tweet_id VARCHAR(32);

ALTER TABLE notes
ADD COLUMN IF NOT EXISTS official_share_x_user_id VARCHAR(32);

ALTER TABLE notes
ADD COLUMN IF NOT EXISTS official_share_set_at TIMESTAMPTZ;

ALTER TABLE notes
ADD COLUMN IF NOT EXISTS official_share_tweet_url TEXT;

ALTER TABLE notes
ADD COLUMN IF NOT EXISTS official_share_x_username VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_notes_official_share_tweet_id
    ON notes(official_share_tweet_id)
    WHERE official_share_tweet_id IS NOT NULL;

COMMENT ON COLUMN notes.official_share_tweet_id IS '販売者が指定した公式リツイート対象のツイートID';
COMMENT ON COLUMN notes.official_share_x_user_id IS '公式ポストの投稿者XユーザーID';
COMMENT ON COLUMN notes.official_share_set_at IS '公式ポストが設定された日時';
COMMENT ON COLUMN notes.official_share_tweet_url IS '公式ポストのURL';
COMMENT ON COLUMN notes.official_share_x_username IS '公式ポストの投稿者Xユーザー名';
