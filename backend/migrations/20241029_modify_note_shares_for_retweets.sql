-- Migration: Adjust note_shares schema for retweet-based unlock

ALTER TABLE note_shares
DROP CONSTRAINT IF EXISTS note_shares_tweet_id_key;

ALTER TABLE note_shares
ADD COLUMN IF NOT EXISTS retweet_tweet_id VARCHAR(255);

ALTER TABLE note_shares
ADD COLUMN IF NOT EXISTS retweet_url TEXT;

CREATE INDEX IF NOT EXISTS idx_note_shares_retweet_tweet_id ON note_shares(retweet_tweet_id);

COMMENT ON COLUMN note_shares.tweet_id IS '公式ポストのツイートID（retweet対象）';
COMMENT ON COLUMN note_shares.retweet_tweet_id IS 'ユーザーが実施したリツイートのツイートID';
COMMENT ON COLUMN note_shares.retweet_url IS 'ユーザーリツイートのURL';
