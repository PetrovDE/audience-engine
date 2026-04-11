-- Migration 009: User and role administration foundation.
-- Mirrors infra/postgres/init/009_user_role_admin_foundation.sql.

CREATE TABLE IF NOT EXISTS ae_users (
    user_id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    email TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT NOT NULL DEFAULT 'system',
    updated_by TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ae_user_role_assignments (
    user_id UUID NOT NULL REFERENCES ae_users(user_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (
        role IN (
            'admin_operator',
            'data_engineer',
            'ml_analyst',
            'campaign_user'
        )
    ),
    assigned_by TEXT NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS ae_user_admin_audit (
    audit_id BIGSERIAL PRIMARY KEY,
    audit_action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    target_user_id UUID REFERENCES ae_users(user_id),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_ae_user_admin_audit_no_update_delete ON ae_user_admin_audit;
CREATE TRIGGER trg_ae_user_admin_audit_no_update_delete
BEFORE UPDATE OR DELETE ON ae_user_admin_audit
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

CREATE INDEX IF NOT EXISTS idx_ae_users_active_created
ON ae_users (is_active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_user_roles_user_assigned
ON ae_user_role_assignments (user_id, assigned_at DESC);

CREATE INDEX IF NOT EXISTS idx_ae_user_admin_audit_target_ts
ON ae_user_admin_audit (target_user_id, action_ts DESC);

