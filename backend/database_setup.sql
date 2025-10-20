-- Ｄ－swipe データベーステーブル作成
-- Supabase SQL Editorで実行してください

-- 1. users テーブル（Supabase Authと連携）
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email VARCHAR(255) UNIQUE NOT NULL,
  username VARCHAR(100) UNIQUE NOT NULL,
  user_type VARCHAR(20) NOT NULL CHECK (user_type IN ('seller', 'buyer')),
  point_balance INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  is_blocked BOOLEAN DEFAULT FALSE,
  blocked_reason TEXT,
  blocked_at TIMESTAMP
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_reason TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMP;

-- 2. landing_pages テーブル
CREATE TABLE IF NOT EXISTS landing_pages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id UUID REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL,
  slug VARCHAR(100) UNIQUE NOT NULL,
  status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
  swipe_direction VARCHAR(20) DEFAULT 'vertical' CHECK (swipe_direction IN ('vertical', 'horizontal')),
  is_fullscreen BOOLEAN DEFAULT false,
  total_views INTEGER DEFAULT 0,
  total_cta_clicks INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 3. lp_steps テーブル
CREATE TABLE IF NOT EXISTS lp_steps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL,
  image_url TEXT NOT NULL,
  video_url TEXT,
  animation_type VARCHAR(50),
  step_views INTEGER DEFAULT 0,
  step_exits INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(lp_id, step_order)
);

-- 4. lp_ctas テーブル
CREATE TABLE IF NOT EXISTS lp_ctas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_id UUID REFERENCES lp_steps(id) ON DELETE SET NULL,
  cta_type VARCHAR(50) NOT NULL,
  button_image_url TEXT NOT NULL,
  button_position VARCHAR(20) DEFAULT 'bottom',
  link_url TEXT,
  is_required BOOLEAN DEFAULT false,
  click_count INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 5. products テーブル
CREATE TABLE IF NOT EXISTS products (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id UUID REFERENCES users(id) ON DELETE CASCADE,
  lp_id UUID REFERENCES landing_pages(id) ON DELETE SET NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  price_in_points INTEGER NOT NULL,
  stock_quantity INTEGER,
  is_available BOOLEAN DEFAULT true,
  total_sales INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 6. point_transactions テーブル
CREATE TABLE IF NOT EXISTS point_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  transaction_type VARCHAR(50) NOT NULL,
  amount INTEGER NOT NULL,
  related_product_id UUID REFERENCES products(id),
  description TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 7. lp_analytics テーブル
CREATE TABLE IF NOT EXISTS lp_analytics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  total_sessions INTEGER DEFAULT 0,
  unique_visitors INTEGER DEFAULT 0,
  avg_time_on_page FLOAT,
  conversion_rate FLOAT,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(lp_id, date)
);

-- 8. ab_tests テーブル
CREATE TABLE IF NOT EXISTS ab_tests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  test_name VARCHAR(255) NOT NULL,
  variant_a_id UUID REFERENCES lp_steps(id),
  variant_b_id UUID REFERENCES lp_steps(id),
  status VARCHAR(20) DEFAULT 'running',
  traffic_split INTEGER DEFAULT 50,
  winner VARCHAR(10),
  created_at TIMESTAMP DEFAULT NOW(),
  ended_at TIMESTAMP
);

-- インデックス作成
CREATE INDEX IF NOT EXISTS idx_landing_pages_seller ON landing_pages(seller_id);
CREATE INDEX IF NOT EXISTS idx_landing_pages_slug ON landing_pages(slug);
CREATE INDEX IF NOT EXISTS idx_landing_pages_status ON landing_pages(status);
CREATE INDEX IF NOT EXISTS idx_lp_steps_lp_id ON lp_steps(lp_id);
CREATE INDEX IF NOT EXISTS idx_lp_steps_order ON lp_steps(lp_id, step_order);
CREATE INDEX IF NOT EXISTS idx_lp_ctas_lp_id ON lp_ctas(lp_id);
CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id);
CREATE INDEX IF NOT EXISTS idx_products_lp ON products(lp_id);
CREATE INDEX IF NOT EXISTS idx_point_transactions_user ON point_transactions(user_id);
CREATE TABLE IF NOT EXISTS moderation_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  action VARCHAR(100) NOT NULL,
  performed_by UUID REFERENCES users(id) ON DELETE SET NULL,
  target_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  target_lp_id UUID REFERENCES landing_pages(id) ON DELETE SET NULL,
  reason TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_moderation_events_created_at ON moderation_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lp_analytics_lp_date ON lp_analytics(lp_id, date);

-- Row Level Security (RLS) 設定
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE landing_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE lp_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE lp_ctas ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE point_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE lp_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE ab_tests ENABLE ROW LEVEL SECURITY;

-- RLS ポリシー: users
CREATE POLICY "Users can view own data" ON users
  FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own data" ON users
  FOR UPDATE USING (auth.uid() = id);

-- RLS ポリシー: landing_pages
CREATE POLICY "Sellers can CRUD own LPs" ON landing_pages
  FOR ALL USING (auth.uid() = seller_id);

CREATE POLICY "Anyone can view published LPs" ON landing_pages
  FOR SELECT USING (status = 'published');

-- RLS ポリシー: lp_steps
CREATE POLICY "Sellers can manage own LP steps" ON lp_steps
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM landing_pages 
      WHERE landing_pages.id = lp_steps.lp_id 
      AND landing_pages.seller_id = auth.uid()
    )
  );

CREATE POLICY "Anyone can view steps of published LPs" ON lp_steps
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM landing_pages 
      WHERE landing_pages.id = lp_steps.lp_id 
      AND landing_pages.status = 'published'
    )
  );

-- RLS ポリシー: lp_ctas
CREATE POLICY "Sellers can manage own LP CTAs" ON lp_ctas
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM landing_pages 
      WHERE landing_pages.id = lp_ctas.lp_id 
      AND landing_pages.seller_id = auth.uid()
    )
  );

CREATE POLICY "Anyone can view CTAs of published LPs" ON lp_ctas
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM landing_pages 
      WHERE landing_pages.id = lp_ctas.lp_id 
      AND landing_pages.status = 'published'
    )
  );

-- RLS ポリシー: products
CREATE POLICY "Sellers can CRUD own products" ON products
  FOR ALL USING (auth.uid() = seller_id);

CREATE POLICY "Anyone can view available products" ON products
  FOR SELECT USING (is_available = true);

-- RLS ポリシー: point_transactions
CREATE POLICY "Users can view own transactions" ON point_transactions
  FOR SELECT USING (auth.uid() = user_id);

-- RLS ポリシー: lp_analytics
CREATE POLICY "Sellers can view own LP analytics" ON lp_analytics
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM landing_pages 
      WHERE landing_pages.id = lp_analytics.lp_id 
      AND landing_pages.seller_id = auth.uid()
    )
  );

-- RLS ポリシー: ab_tests
CREATE POLICY "Sellers can manage own AB tests" ON ab_tests
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM landing_pages 
      WHERE landing_pages.id = ab_tests.lp_id 
      AND landing_pages.seller_id = auth.uid()
    )
  );

-- 完了メッセージ
DO $$
BEGIN
  RAISE NOTICE 'Ｄ－swipe データベーステーブルの作成が完了しました！';
  RAISE NOTICE '8つのテーブルとインデックス、RLSポリシーが設定されました。';
END $$;
