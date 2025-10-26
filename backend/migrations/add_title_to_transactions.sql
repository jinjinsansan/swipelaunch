-- Add title column to one_lat_transactions table

ALTER TABLE one_lat_transactions 
ADD COLUMN IF NOT EXISTS title TEXT;

-- Add comment
COMMENT ON COLUMN one_lat_transactions.title IS 'Transaction title/description';
