-- Migration: NOTE Share System (X/Twitter Share to Unlock)
-- 有料NOTEをXでシェアして無料解放 + インフォプレナーにポイント報酬

-- ========================================
-- 1. X連携テーブル
-- ========================================
CREATE TABLE IF NOT EXISTS user_x_connections (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    x_user_id VARCHAR(255) NOT NULL UNIQUE,
    x_username VARCHAR(255) NOT NULL,
    access_token TEXT NOT NULL,                -- 暗号化推奨
    refresh_token TEXT,                        -- 暗号化推奨
    token_expires_at TIMESTAMPTZ,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    last_used_at TIMESTAMPTZ,
    
    -- 不正検知用のXアカウント情報
    account_created_at TIMESTAMPTZ,            -- Xアカウント作成日
    followers_count INTEGER DEFAULT 0,
    is_verified BOOLEAN DEFAULT FALSE          -- X認証バッジ
);

CREATE INDEX IF NOT EXISTS idx_user_x_connections_x_user_id ON user_x_connections(x_user_id);

-- ========================================
-- 2. NOTEシェア記録テーブル
-- ========================================
CREATE TABLE IF NOT EXISTS note_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- ツイート情報
    tweet_id VARCHAR(255) NOT NULL UNIQUE,
    tweet_url TEXT NOT NULL,
    
    -- 検証・報酬
    shared_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    points_rewarded BOOLEAN NOT NULL DEFAULT FALSE,
    points_amount INTEGER DEFAULT 0,
    
    -- 不正検知用
    ip_address VARCHAR(45),
    user_agent TEXT,
    is_suspicious BOOLEAN NOT NULL DEFAULT FALSE,
    admin_notes TEXT,
    
    -- 1ユーザー1記事1回まで
    CONSTRAINT note_shares_unique UNIQUE(note_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_note_shares_note_id ON note_shares(note_id);
CREATE INDEX IF NOT EXISTS idx_note_shares_user_id ON note_shares(user_id);
CREATE INDEX IF NOT EXISTS idx_note_shares_tweet_id ON note_shares(tweet_id);
CREATE INDEX IF NOT EXISTS idx_note_shares_suspicious ON note_shares(is_suspicious) WHERE is_suspicious = TRUE;
CREATE INDEX IF NOT EXISTS idx_note_shares_created_at ON note_shares(shared_at DESC);

-- ========================================
-- 3. シェア報酬設定テーブル
-- ========================================
CREATE TABLE IF NOT EXISTS share_reward_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    points_per_share INTEGER NOT NULL DEFAULT 1,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- 初期データ: 1シェア = 1ポイント
INSERT INTO share_reward_settings (points_per_share)
VALUES (1)
ON CONFLICT DO NOTHING;

-- ========================================
-- 4. 不正検知アラートテーブル
-- ========================================
CREATE TABLE IF NOT EXISTS share_fraud_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type VARCHAR(50) NOT NULL,           -- 'rapid_shares', 'same_ip', 'deleted_tweet', 'suspicious_account'
    note_share_id UUID REFERENCES note_shares(id) ON DELETE CASCADE,
    note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',  -- 'low', 'medium', 'high'
    description TEXT,
    
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_fraud_alerts_unresolved ON share_fraud_alerts(resolved) WHERE resolved = FALSE;
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_severity ON share_fraud_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_created_at ON share_fraud_alerts(created_at DESC);

-- ========================================
-- 5. notesテーブル拡張: シェア解放許可フラグ
-- ========================================
ALTER TABLE notes
ADD COLUMN IF NOT EXISTS allow_share_unlock BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN notes.allow_share_unlock IS 'Xシェアで無料解放を許可するか（デフォルト: FALSE）';

-- ========================================
-- 6. トランザクションタイプの追加準備
-- ========================================
-- point_transactionsテーブルには既に related_note_id カラムがあるため、
-- transaction_type = 'note_share_reward' を使用する
COMMENT ON TABLE note_shares IS 'NOTEのXシェア記録。1ユーザー1記事につき1回までシェア可能。';
COMMENT ON TABLE user_x_connections IS 'ユーザーのX (Twitter) 連携情報。OAuth 2.0トークンを保存。';
COMMENT ON TABLE share_reward_settings IS 'シェア報酬レート設定（管理者が変更可能）';
COMMENT ON TABLE share_fraud_alerts IS 'シェア不正検知アラート。疑わしいシェアパターンを記録。';
