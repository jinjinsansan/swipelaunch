-- note_sharesテーブルにリポストモード追加
-- ツイート投稿 vs リポスト を区別

ALTER TABLE note_shares
ADD COLUMN IF NOT EXISTS share_mode VARCHAR(20) NOT NULL DEFAULT 'tweet',
ADD COLUMN IF NOT EXISTS retweeted_post_id TEXT; -- リポストした公式投稿のID

COMMENT ON COLUMN note_shares.share_mode IS 'シェア方式: tweet=自分でツイート投稿, repost=公式投稿をRT';
COMMENT ON COLUMN note_shares.retweeted_post_id IS 'リポストした公式投稿のツイートID（repostモードの場合）';

-- インデックス追加
CREATE INDEX IF NOT EXISTS idx_note_shares_share_mode ON note_shares(share_mode);
