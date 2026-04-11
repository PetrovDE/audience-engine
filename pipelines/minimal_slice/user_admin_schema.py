from __future__ import annotations

from .access_roles import ROLE_VALUES
from .control_plane_registry_db import load_psycopg, postgres_conninfo

_SCHEMA_READY = False


def _role_constraint_sql() -> str:
    return ", ".join(f"'{role}'" for role in ROLE_VALUES)


def ensure_user_admin_schema(*, force: bool = False) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY and not force:
        return

    role_constraint = _role_constraint_sql()
    psycopg, _dict_row = load_psycopg()
    with psycopg.connect(postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS ae_user_role_assignments (
                    user_id UUID NOT NULL
                        REFERENCES ae_users(user_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ({role_constraint})),
                    assigned_by TEXT NOT NULL,
                    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, role)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ae_user_admin_audit (
                    audit_id BIGSERIAL PRIMARY KEY,
                    audit_action TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    target_user_id UUID REFERENCES ae_users(user_id),
                    details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    action_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION forbid_audience_audit_mutation()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION 'audience audit tables are append-only';
                END;
                $$;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS trg_ae_user_admin_audit_no_update_delete
                ON ae_user_admin_audit;
                """
            )
            cur.execute(
                """
                CREATE TRIGGER trg_ae_user_admin_audit_no_update_delete
                BEFORE UPDATE OR DELETE ON ae_user_admin_audit
                FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ae_users_active_created
                ON ae_users (is_active, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ae_user_roles_user_assigned
                ON ae_user_role_assignments (user_id, assigned_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ae_user_admin_audit_target_ts
                ON ae_user_admin_audit (target_user_id, action_ts DESC);
                """
            )
        conn.commit()
    _SCHEMA_READY = True
