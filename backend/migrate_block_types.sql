-- 既存の LP ステップで block_type が NULL のものを、content_data の block_type から更新
-- このスクリプトを Supabase の SQL コンソールで実行してください

UPDATE lp_steps
SET block_type = content_data->>'block_type'
WHERE block_type IS NULL 
  AND content_data IS NOT NULL 
  AND content_data->>'block_type' IS NOT NULL 
  AND trim(content_data->>'block_type') != '';

-- 結果を確認
SELECT 
  COUNT(*) as updated_count,
  MAX(updated_at) as last_updated
FROM lp_steps
WHERE block_type IS NOT NULL 
  AND content_data IS NOT NULL 
  AND content_data->>'block_type' IS NOT NULL;
