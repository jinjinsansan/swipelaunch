-- Create tables for salon roles and role assignments

CREATE TABLE IF NOT EXISTS salon_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    manage_feed BOOLEAN NOT NULL DEFAULT FALSE,
    manage_events BOOLEAN NOT NULL DEFAULT FALSE,
    manage_assets BOOLEAN NOT NULL DEFAULT FALSE,
    manage_announcements BOOLEAN NOT NULL DEFAULT FALSE,
    manage_members BOOLEAN NOT NULL DEFAULT FALSE,
    manage_roles BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(salon_id, name)
);

CREATE INDEX IF NOT EXISTS idx_salon_roles_salon ON salon_roles(salon_id);

DROP TRIGGER IF EXISTS trg_salon_roles_updated_at ON salon_roles;
CREATE TRIGGER trg_salon_roles_updated_at
BEFORE UPDATE ON salon_roles
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();

ALTER TABLE salon_roles ENABLE ROW LEVEL SECURITY;


CREATE TABLE IF NOT EXISTS salon_member_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salon_id UUID NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES salon_roles(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(salon_id, role_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_salon_member_roles_salon ON salon_member_roles(salon_id);
CREATE INDEX IF NOT EXISTS idx_salon_member_roles_user ON salon_member_roles(user_id);

DROP TRIGGER IF EXISTS trg_salon_member_roles_updated_at ON salon_member_roles;
CREATE TRIGGER trg_salon_member_roles_updated_at
BEFORE UPDATE ON salon_member_roles
FOR EACH ROW
EXECUTE PROCEDURE set_subscription_updated_at();

ALTER TABLE salon_member_roles ENABLE ROW LEVEL SECURITY;
