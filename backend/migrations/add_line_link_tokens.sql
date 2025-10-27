-- LINE連携トークンテーブル
-- ユーザーがLINE追加する時に使うユニークなトークンを管理

CREATE TABLE IF NOT EXISTS line_link_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    line_user_id TEXT,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- インデックス作成
CREATE INDEX IF NOT EXISTS idx_line_link_tokens_token ON line_link_tokens(token);
CREATE INDEX IF NOT EXISTS idx_line_link_tokens_user_id ON line_link_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_line_link_tokens_expires_at ON line_link_tokens(expires_at);

-- RLSポリシー
ALTER TABLE line_link_tokens ENABLE ROW LEVEL SECURITY;

-- ユーザーは自分のトークンのみ作成・参照可能
CREATE POLICY "Users can create their own tokens"
    ON line_link_tokens FOR INSERT
    WITH CHECK (auth.uid()::text = user_id::text);

CREATE POLICY "Users can view their own tokens"
    ON line_link_tokens FOR SELECT
    USING (auth.uid()::text = user_id::text);

-- サービスロールは全アクセス可能（Webhook処理用）
CREATE POLICY "Service role has full access to line_link_tokens"
    ON line_link_tokens FOR ALL
    USING (true)
    WITH CHECK (true);

COMMENT ON TABLE line_link_tokens IS 'LINE連携用のユニークトークン管理';
COMMENT ON COLUMN line_link_tokens.token IS 'URLに含めるユニークなトークン';
COMMENT ON COLUMN line_link_tokens.expires_at IS 'トークンの有効期限（24時間）';
COMMENT ON COLUMN line_link_tokens.used IS 'トークンが使用されたかどうか';
COMMENT ON COLUMN line_link_tokens.line_user_id IS '連携されたLINEユーザーID';
COMMENT ON COLUMN line_link_tokens.used_at IS 'トークンが使用された日時';
