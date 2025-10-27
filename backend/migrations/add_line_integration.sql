-- LINE連携機能のためのテーブル作成

-- 1. LINE連携状態テーブル
CREATE TABLE IF NOT EXISTS line_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    line_user_id VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255),
    picture_url TEXT,
    status_message TEXT,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bonus_awarded BOOLEAN NOT NULL DEFAULT FALSE,
    bonus_points INTEGER,
    bonus_awarded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id)
);

-- 2. LINEボーナス設定テーブル（管理者が設定）
CREATE TABLE IF NOT EXISTS line_bonus_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bonus_points INTEGER NOT NULL DEFAULT 300,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT DEFAULT 'LINE公式アカウントを追加して300ポイントGET！',
    line_add_url TEXT NOT NULL DEFAULT 'https://lin.ee/JFvc4dE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- デフォルト設定を挿入
INSERT INTO line_bonus_settings (bonus_points, is_enabled, description, line_add_url)
VALUES (300, TRUE, 'LINE公式アカウントを追加して300ポイントGET！', 'https://lin.ee/JFvc4dE')
ON CONFLICT DO NOTHING;

-- インデックス作成
CREATE INDEX IF NOT EXISTS idx_line_connections_user_id ON line_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_line_connections_line_user_id ON line_connections(line_user_id);
CREATE INDEX IF NOT EXISTS idx_line_connections_bonus_awarded ON line_connections(bonus_awarded);

-- RLSポリシー設定
ALTER TABLE line_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE line_bonus_settings ENABLE ROW LEVEL SECURITY;

-- line_connections: ユーザーは自分のデータのみ閲覧可能
CREATE POLICY "Users can view own line connection"
    ON line_connections FOR SELECT
    USING (auth.uid() = user_id);

-- line_bonus_settings: 全員が閲覧可能（ボーナス情報を表示するため）
CREATE POLICY "Anyone can view line bonus settings"
    ON line_bonus_settings FOR SELECT
    USING (TRUE);

-- 管理者のみが設定を変更可能
CREATE POLICY "Admins can update line bonus settings"
    ON line_bonus_settings FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE users.id = auth.uid()
            AND users.user_type = 'admin'
        )
    );

-- 管理者はすべてのLINE連携を閲覧可能
CREATE POLICY "Admins can view all line connections"
    ON line_connections FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE users.id = auth.uid()
            AND users.user_type = 'admin'
        )
    );

-- トリガー: updated_at自動更新
CREATE OR REPLACE FUNCTION update_line_connections_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_line_connections_updated_at
    BEFORE UPDATE ON line_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_line_connections_updated_at();

CREATE OR REPLACE FUNCTION update_line_bonus_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_line_bonus_settings_updated_at
    BEFORE UPDATE ON line_bonus_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_line_bonus_settings_updated_at();

COMMENT ON TABLE line_connections IS 'LINE連携状態とボーナス付与履歴';
COMMENT ON TABLE line_bonus_settings IS 'LINE連携ボーナスの管理者設定';
