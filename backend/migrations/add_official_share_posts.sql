-- 公式シェア投稿テーブル
-- 著者が作成した「この投稿をRTしてね」用の公式投稿を管理

CREATE TABLE IF NOT EXISTS official_share_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tweet_id TEXT NOT NULL, -- 公式投稿のツイートID
    tweet_url TEXT NOT NULL, -- 公式投稿のURL
    tweet_text TEXT NOT NULL, -- 投稿テキスト
    is_active BOOLEAN NOT NULL DEFAULT true, -- アクティブかどうか
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    UNIQUE(note_id, is_active), -- 1つのNOTEにつき1つのアクティブな公式投稿のみ
    CONSTRAINT fk_note FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    CONSTRAINT fk_author FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_official_share_posts_note_id ON official_share_posts(note_id);
CREATE INDEX idx_official_share_posts_author_id ON official_share_posts(author_id);
CREATE INDEX idx_official_share_posts_is_active ON official_share_posts(is_active);

COMMENT ON TABLE official_share_posts IS '著者が作成した公式シェア投稿（note.comのリポスト方式用）';
COMMENT ON COLUMN official_share_posts.tweet_id IS 'X（Twitter）の投稿ID';
COMMENT ON COLUMN official_share_posts.is_active IS 'false = 削除済み、新しい公式投稿を作成時に古いものはfalseになる';
