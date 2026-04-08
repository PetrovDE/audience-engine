-- Migration 004: append-only audit trail for lifecycle operations.
-- This migration mirrors infra/postgres/init/004_index_lifecycle_audit.sql.

CREATE TABLE IF NOT EXISTS index_lifecycle_audit (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL CHECK (
        action IN ('validate_generation', 'promote_alias', 'rollback_alias')
    ),
    alias_name TEXT NOT NULL,
    target_collection_name TEXT,
    previous_collection_name TEXT,
    actor_role TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failed')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION forbid_index_lifecycle_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'index_lifecycle_audit is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_index_lifecycle_audit_no_update_delete
ON index_lifecycle_audit;

CREATE TRIGGER trg_index_lifecycle_audit_no_update_delete
BEFORE UPDATE OR DELETE ON index_lifecycle_audit
FOR EACH ROW EXECUTE FUNCTION forbid_index_lifecycle_audit_mutation();

CREATE INDEX IF NOT EXISTS idx_index_lifecycle_audit_alias_ts
ON index_lifecycle_audit (alias_name, action_ts DESC);
