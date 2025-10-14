-- テンプレートシステム用のカラム追加

-- lp_stepsテーブルにcontent_dataカラム追加
ALTER TABLE lp_steps 
ADD COLUMN IF NOT EXISTS content_data JSONB DEFAULT '{}'::jsonb;

-- content_dataの構造説明
COMMENT ON COLUMN lp_steps.content_data IS 'テンプレートブロックの内容 (JSON): {blockType, templateId, content: {title, subtitle, text, imageUrl, backgroundColor, textColor, etc}}';

-- image_urlをオプショナルに変更（テンプレートベースではimage_urlが不要な場合がある）
ALTER TABLE lp_steps 
ALTER COLUMN image_url DROP NOT NULL;

-- テンプレート使用状況を記録する新テーブル作成
CREATE TABLE IF NOT EXISTS template_blocks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_id VARCHAR(50) NOT NULL,
  template_type VARCHAR(50) NOT NULL,
  category VARCHAR(50) NOT NULL,
  name VARCHAR(100) NOT NULL,
  description TEXT,
  thumbnail_url TEXT,
  default_content JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active BOOLEAN DEFAULT true,
  usage_count INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

-- インデックス追加
CREATE INDEX IF NOT EXISTS idx_template_blocks_type ON template_blocks(template_type);
CREATE INDEX IF NOT EXISTS idx_template_blocks_category ON template_blocks(category);
CREATE INDEX IF NOT EXISTS idx_lp_steps_content_data ON lp_steps USING gin(content_data);

-- AI生成履歴テーブル
CREATE TABLE IF NOT EXISTS ai_generations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  generation_type VARCHAR(50) NOT NULL, -- 'headline', 'description', 'structure', 'cta'
  prompt TEXT NOT NULL,
  generated_content TEXT NOT NULL,
  was_used BOOLEAN DEFAULT false,
  created_at TIMESTAMP DEFAULT NOW()
);

-- インデックス追加
CREATE INDEX IF NOT EXISTS idx_ai_generations_user_id ON ai_generations(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_generations_lp_id ON ai_generations(lp_id);
CREATE INDEX IF NOT EXISTS idx_ai_generations_type ON ai_generations(generation_type);

-- CTAボタンスタイルテーブル
CREATE TABLE IF NOT EXISTS cta_button_styles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  style_id VARCHAR(50) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL,
  preview_image_url TEXT,
  css_classes TEXT NOT NULL,
  default_colors JSONB NOT NULL DEFAULT '{}'::jsonb,
  usage_count INTEGER DEFAULT 0,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

-- RLS (Row Level Security) ポリシー
ALTER TABLE ai_generations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own AI generations"
  ON ai_generations FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own AI generations"
  ON ai_generations FOR INSERT
  WITH CHECK (auth.uid() = user_id);

-- サンプルテンプレートデータ挿入
INSERT INTO template_blocks (template_id, template_type, category, name, description, default_content) VALUES
  ('hero-1', 'hero', 'header', 'センター配置ヒーロー', 'シンプルな中央揃えヒーローセクション', 
   '{"title": "あなたの見出しをここに", "subtitle": "サブタイトル", "backgroundColor": "#000000", "textColor": "#FFFFFF", "buttonText": "今すぐ始める", "buttonColor": "#3B82F6"}'::jsonb),
  
  ('hero-2', 'hero', 'header', '左右分割ヒーロー', 'テキストと画像を左右に配置', 
   '{"title": "魅力的な見出し", "subtitle": "詳しい説明", "imageUrl": "", "backgroundColor": "#FFFFFF", "textColor": "#000000", "buttonText": "詳しく見る", "buttonColor": "#10B981"}'::jsonb),
  
  ('text-img-1', 'text-image', 'content', '左テキスト右画像', 'テキストを左、画像を右に配置', 
   '{"title": "特徴タイトル", "text": "詳しい説明文がここに入ります", "imageUrl": "", "backgroundColor": "#F9FAFB", "textColor": "#111827"}'::jsonb),
  
  ('pricing-1', 'pricing', 'conversion', '3カラム価格表', '3つのプランを並べて表示', 
   '{"plans": [{"name": "ベーシック", "price": "1000", "features": ["機能1", "機能2"]}, {"name": "プロ", "price": "3000", "features": ["機能1", "機能2", "機能3"]}, {"name": "エンタープライズ", "price": "お問い合わせ", "features": ["全機能"]}]}'::jsonb),
  
  ('testimonial-1', 'testimonials', 'social-proof', 'お客様の声カード', '顧客レビューをカード形式で表示', 
   '{"testimonials": [{"name": "田中様", "role": "30代女性", "text": "素晴らしい商品です！", "imageUrl": "", "rating": 5}]}'::jsonb),
  
  ('faq-1', 'faq', 'content', 'FAQアコーディオン', 'よくある質問をアコーディオン形式で', 
   '{"faqs": [{"question": "質問1", "answer": "回答1"}, {"question": "質問2", "answer": "回答2"}]}'::jsonb),
  
  ('cta-1', 'cta', 'conversion', 'シンプルCTA', '大きなボタンでアクションを促進', 
   '{"title": "今すぐ始めましょう", "subtitle": "無料トライアル実施中", "buttonText": "無料で試す", "buttonColor": "#EF4444", "backgroundColor": "#FEF2F2"}'::jsonb);

-- サンプルCTAボタンスタイル
INSERT INTO cta_button_styles (style_id, name, css_classes, default_colors) VALUES
  ('btn-primary', 'プライマリーボタン', 'px-8 py-4 rounded-lg font-bold shadow-lg hover:scale-105 transition-transform', 
   '{"background": "#3B82F6", "text": "#FFFFFF"}'::jsonb),
  
  ('btn-success', '成功ボタン', 'px-8 py-4 rounded-full font-bold shadow-lg hover:shadow-xl transition-shadow', 
   '{"background": "#10B981", "text": "#FFFFFF"}'::jsonb),
  
  ('btn-danger', '強調ボタン', 'px-10 py-5 rounded-lg font-bold text-xl shadow-2xl hover:brightness-110 transition-all', 
   '{"background": "#EF4444", "text": "#FFFFFF"}'::jsonb),
  
  ('btn-outline', 'アウトラインボタン', 'px-8 py-4 rounded-lg font-bold border-2 hover:bg-opacity-10 transition-colors', 
   '{"background": "transparent", "text": "#3B82F6", "border": "#3B82F6"}'::jsonb),
  
  ('btn-gradient', 'グラデーションボタン', 'px-8 py-4 rounded-lg font-bold shadow-lg hover:scale-105 transition-transform bg-gradient-to-r', 
   '{"from": "#8B5CF6", "to": "#EC4899", "text": "#FFFFFF"}'::jsonb);

COMMENT ON TABLE template_blocks IS 'テンプレートブロック定義';
COMMENT ON TABLE ai_generations IS 'AI生成履歴';
COMMENT ON TABLE cta_button_styles IS 'CTAボタンスタイル定義';
