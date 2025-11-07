-- Account sharing tables allow owners to delegate full access to other users

CREATE TABLE IF NOT EXISTS account_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delegate_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    invite_token UUID NOT NULL UNIQUE,
    invited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT account_shares_status_check CHECK (status IN ('pending', 'active', 'revoked')),
    CONSTRAINT account_shares_owner_delegate_unique UNIQUE (owner_user_id, delegate_user_id)
);

CREATE INDEX IF NOT EXISTS idx_account_shares_owner ON account_shares(owner_user_id, status);
CREATE INDEX IF NOT EXISTS idx_account_shares_delegate ON account_shares(delegate_user_id, status);
CREATE INDEX IF NOT EXISTS idx_account_shares_expires ON account_shares(expires_at) WHERE status = 'pending';


ALTER TABLE account_shares ENABLE ROW LEVEL SECURITY;
