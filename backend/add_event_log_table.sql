-- イベントログテーブル追加
-- Supabase SQL Editorで実行してください

-- lp_event_logs テーブル（個別イベント記録用）
CREATE TABLE IF NOT EXISTS lp_event_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_id UUID REFERENCES lp_steps(id) ON DELETE SET NULL,
  cta_id UUID REFERENCES lp_ctas(id) ON DELETE SET NULL,
  event_type VARCHAR(50) NOT NULL CHECK (event_type IN ('view', 'step_view', 'step_exit', 'cta_click')),
  session_id VARCHAR(255),
  user_agent TEXT,
  ip_address VARCHAR(45),
  created_at TIMESTAMP DEFAULT NOW()
);

-- インデックス作成（パフォーマンス向上）
CREATE INDEX IF NOT EXISTS idx_lp_event_logs_lp_id ON lp_event_logs(lp_id);
CREATE INDEX IF NOT EXISTS idx_lp_event_logs_event_type ON lp_event_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_lp_event_logs_session_id ON lp_event_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_lp_event_logs_created_at ON lp_event_logs(created_at);

-- RLSポリシー（公開API用）
ALTER TABLE lp_event_logs ENABLE ROW LEVEL SECURITY;

-- 全員が挿入可能（イベント記録用）
CREATE POLICY "Anyone can insert event logs"
ON lp_event_logs FOR INSERT
WITH CHECK (true);

-- Seller は自分のLPのイベントログを閲覧可能
CREATE POLICY "Sellers can view their LP event logs"
ON lp_event_logs FOR SELECT
USING (
  EXISTS (
    SELECT 1 FROM landing_pages
    WHERE landing_pages.id = lp_event_logs.lp_id
    AND landing_pages.seller_id = auth.uid()
  )
);

-- Service role は全てのイベントログにアクセス可能（管理用）
CREATE POLICY "Service role can manage all event logs"
ON lp_event_logs FOR ALL
USING (auth.jwt() ->> 'role' = 'service_role');
