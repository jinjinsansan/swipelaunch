-- lp_stepsテーブルにcontent_dataフィールドを追加

ALTER TABLE lp_steps 
ADD COLUMN content_data JSONB DEFAULT '{}'::jsonb,
ADD COLUMN block_type VARCHAR(50);

-- 既存のデータに対して空のJSONを設定
UPDATE lp_steps SET content_data = '{}'::jsonb WHERE content_data IS NULL;

-- インデックスを追加（JSONB検索の高速化）
CREATE INDEX idx_lp_steps_content_data ON lp_steps USING GIN (content_data);

COMMENT ON COLUMN lp_steps.content_data IS 'ブロックのコンテンツデータ（テンプレートシステム用）';
COMMENT ON COLUMN lp_steps.block_type IS 'ブロックタイプ（hero-1, pricing-2など）';
