-- Maintenance modes and system status tracking

CREATE TABLE IF NOT EXISTS maintenance_modes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope TEXT NOT NULL CHECK (scope IN (
        'global', 'lp', 'note', 'salon', 'points', 'products', 'ai', 'payments'
    )),
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN (
        'scheduled', 'active', 'completed', 'cancelled'
    )),
    title TEXT NOT NULL,
    message TEXT,
    planned_start TIMESTAMPTZ,
    planned_end TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    deactivated_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maintenance_modes_scope ON maintenance_modes(scope);
CREATE INDEX IF NOT EXISTS idx_maintenance_modes_status ON maintenance_modes(status);
CREATE INDEX IF NOT EXISTS idx_maintenance_modes_planned ON maintenance_modes(planned_start);

CREATE TABLE IF NOT EXISTS system_status_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    response_time_ms INTEGER,
    message TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_system_status_checks_component ON system_status_checks(component);
CREATE INDEX IF NOT EXISTS idx_system_status_checks_checked_at ON system_status_checks(checked_at DESC);

CREATE OR REPLACE FUNCTION set_maintenance_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_maintenance_modes_updated_at ON maintenance_modes;
CREATE TRIGGER trg_maintenance_modes_updated_at
BEFORE UPDATE ON maintenance_modes
FOR EACH ROW
EXECUTE PROCEDURE set_maintenance_updated_at();
