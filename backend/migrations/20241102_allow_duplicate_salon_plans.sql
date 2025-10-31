-- Allow multiple salons to reuse the same subscription plan id

ALTER TABLE salons
    DROP CONSTRAINT IF EXISTS salons_subscription_plan_id_key;

-- In case a unique index was created separately, drop it as well
DROP INDEX IF EXISTS idx_unique_salons_subscription_plan_id;
