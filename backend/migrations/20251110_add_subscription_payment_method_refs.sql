-- Add payment method references for subscription sessions and user subscriptions

ALTER TABLE one_lat_subscription_sessions
    ADD COLUMN IF NOT EXISTS payment_method_record_id UUID REFERENCES one_lat_payment_methods(id);

CREATE INDEX IF NOT EXISTS idx_subscription_sessions_payment_method_record
    ON one_lat_subscription_sessions(payment_method_record_id)
    WHERE payment_method_record_id IS NOT NULL;

ALTER TABLE user_subscriptions
    ADD COLUMN IF NOT EXISTS payment_method_record_id UUID REFERENCES one_lat_payment_methods(id);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_payment_method_record
    ON user_subscriptions(payment_method_record_id)
    WHERE payment_method_record_id IS NOT NULL;
