-- Add product_id to landing_pages table
-- This links each LP to a specific product for CTA buttons

ALTER TABLE landing_pages 
ADD COLUMN product_id UUID REFERENCES products(id) ON DELETE SET NULL;

-- Add index for faster lookups
CREATE INDEX idx_landing_pages_product_id ON landing_pages(product_id);

-- Comment
COMMENT ON COLUMN landing_pages.product_id IS 'Associated product for CTA buttons';
