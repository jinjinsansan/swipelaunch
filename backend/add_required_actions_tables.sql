-- 必須アクションテーブル追加
-- Supabase SQL Editorで実行してください

-- lp_required_actions テーブル（LPに必須アクションを設定）
CREATE TABLE IF NOT EXISTS lp_required_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_id UUID REFERENCES lp_steps(id) ON DELETE CASCADE,
  action_type VARCHAR(50) NOT NULL CHECK (action_type IN ('email', 'line', 'form')),
  action_config JSONB,
  is_required BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

-- user_action_completions テーブル（ユーザーのアクション完了記録）
CREATE TABLE IF NOT EXISTS user_action_completions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  action_id UUID REFERENCES lp_required_actions(id) ON DELETE CASCADE,
  session_id VARCHAR(255),
  action_type VARCHAR(50) NOT NULL,
  action_data JSONB,
  completed_at TIMESTAMP DEFAULT NOW()
);

-- インデックス作成
CREATE INDEX IF NOT EXISTS idx_lp_required_actions_lp_id ON lp_required_actions(lp_id);
CREATE INDEX IF NOT EXISTS idx_lp_required_actions_step_id ON lp_required_actions(step_id);
CREATE INDEX IF NOT EXISTS idx_user_action_completions_lp_id ON user_action_completions(lp_id);
CREATE INDEX IF NOT EXISTS idx_user_action_completions_session_id ON user_action_completions(session_id);

-- RLSポリシー
ALTER TABLE lp_required_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_action_completions ENABLE ROW LEVEL SECURITY;

-- lp_required_actions: Sellerは自分のLPのアクションを管理可能
CREATE POLICY "Sellers can manage their LP required actions"
ON lp_required_actions FOR ALL
USING (
  EXISTS (
    SELECT 1 FROM landing_pages
    WHERE landing_pages.id = lp_required_actions.lp_id
    AND landing_pages.seller_id = auth.uid()
  )
);

-- lp_required_actions: 公開LPのアクションは誰でも読み取り可能
CREATE POLICY "Anyone can view published LP required actions"
ON lp_required_actions FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM landing_pages
    WHERE landing_pages.id = lp_required_actions.lp_id
    AND landing_pages.status = 'published'
  )
);

-- user_action_completions: 誰でも挿入可能（アクション完了記録用）
CREATE POLICY "Anyone can insert action completions"
ON user_action_completions FOR INSERT
WITH CHECK (true);

-- user_action_completions: Sellerは自分のLPのアクション完了を閲覧可能
CREATE POLICY "Sellers can view their LP action completions"
ON user_action_completions FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM landing_pages
    WHERE landing_pages.id = user_action_completions.lp_id
    AND landing_pages.seller_id = auth.uid()
  )
);

-- Service role は全てにアクセス可能
CREATE POLICY "Service role can manage all required actions"
ON lp_required_actions FOR ALL
USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service role can manage all action completions"
ON user_action_completions FOR ALL
USING (auth.jwt() ->> 'role' = 'service_role');
