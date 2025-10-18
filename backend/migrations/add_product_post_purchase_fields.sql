-- Add post-purchase redirect fields to products table
ALTER TABLE products
ADD COLUMN IF NOT EXISTS redirect_url TEXT,
ADD COLUMN IF NOT EXISTS thanks_lp_id UUID REFERENCES landing_pages(id) ON DELETE SET NULL;

-- Add comment for clarity
COMMENT ON COLUMN products.redirect_url IS '購入完了後のリダイレクトURL（外部URL）';
COMMENT ON COLUMN products.thanks_lp_id IS '購入完了後のサンクスページLP ID（サイト内）';
