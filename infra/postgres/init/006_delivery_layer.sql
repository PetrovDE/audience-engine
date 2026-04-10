CREATE TABLE IF NOT EXISTS audience_delivery_job (
    delivery_job_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    campaign_id TEXT NOT NULL,
    delivery_target_id TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    requested_by_role TEXT NOT NULL,
    requested_by_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'materialized', 'delivered', 'failed', 'skipped_conflict', 'skipped_no_source_rows')
    ),
    source_row_count INTEGER NOT NULL DEFAULT 0 CHECK (source_row_count >= 0),
    rows_materialized INTEGER NOT NULL DEFAULT 0 CHECK (rows_materialized >= 0),
    rows_delivered INTEGER NOT NULL DEFAULT 0 CHECK (rows_delivered >= 0),
    rows_skipped_conflict INTEGER NOT NULL DEFAULT 0 CHECK (rows_skipped_conflict >= 0),
    artifact_uri TEXT,
    error_detail TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    materialized_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audience_delivery_attempt (
    id BIGSERIAL PRIMARY KEY,
    delivery_job_id UUID NOT NULL REFERENCES audience_delivery_job(delivery_job_id),
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    campaign_id TEXT NOT NULL,
    delivery_target_id TEXT NOT NULL,
    attempt_status TEXT NOT NULL CHECK (
        attempt_status IN ('pending', 'materialized', 'delivered', 'failed', 'skipped_conflict', 'skipped_no_source_rows')
    ),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempt_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audience_delivery_record (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    campaign_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    delivery_target_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    integration_profile_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    export_target_id TEXT NOT NULL,
    delivery_status TEXT NOT NULL CHECK (
        delivery_status IN ('pending', 'materialized', 'delivered', 'failed', 'skipped_conflict', 'skipped_no_source_rows')
    ),
    delivery_job_id UUID NOT NULL REFERENCES audience_delivery_job(delivery_job_id),
    delivery_artifact_uri TEXT,
    delivery_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    staging_exported_ts TIMESTAMPTZ NOT NULL,
    materialized_ts TIMESTAMPTZ,
    delivered_ts TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, customer_id, delivery_target_id)
);

CREATE TABLE IF NOT EXISTS audience_crm_postgres_outbox (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    campaign_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    delivery_target_id TEXT NOT NULL,
    delivery_job_id UUID NOT NULL REFERENCES audience_delivery_job(delivery_job_id),
    outbox_status TEXT NOT NULL CHECK (
        outbox_status IN ('pending', 'materialized', 'delivered', 'failed', 'skipped_conflict', 'skipped_no_source_rows')
    ),
    policy_version TEXT NOT NULL,
    integration_profile_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    export_target_id TEXT NOT NULL,
    staging_exported_ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, customer_id, delivery_target_id)
);

DROP TRIGGER IF EXISTS trg_audience_delivery_attempt_no_update_delete ON audience_delivery_attempt;
CREATE TRIGGER trg_audience_delivery_attempt_no_update_delete
BEFORE UPDATE OR DELETE ON audience_delivery_attempt
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

DROP TRIGGER IF EXISTS trg_audience_delivery_record_no_update_delete ON audience_delivery_record;
CREATE TRIGGER trg_audience_delivery_record_no_update_delete
BEFORE UPDATE OR DELETE ON audience_delivery_record
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

DROP TRIGGER IF EXISTS trg_audience_crm_postgres_outbox_no_update_delete ON audience_crm_postgres_outbox;
CREATE TRIGGER trg_audience_crm_postgres_outbox_no_update_delete
BEFORE UPDATE OR DELETE ON audience_crm_postgres_outbox
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

CREATE INDEX IF NOT EXISTS idx_delivery_job_run_started
ON audience_delivery_job (run_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_delivery_job_target_started
ON audience_delivery_job (delivery_target_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_delivery_attempt_run_ts
ON audience_delivery_attempt (run_id, attempt_ts DESC);

CREATE INDEX IF NOT EXISTS idx_delivery_attempt_job_ts
ON audience_delivery_attempt (delivery_job_id, attempt_ts DESC);

CREATE INDEX IF NOT EXISTS idx_delivery_record_run_target
ON audience_delivery_record (run_id, delivery_target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_delivery_record_campaign_target
ON audience_delivery_record (campaign_id, delivery_target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_delivery_record_customer
ON audience_delivery_record (customer_id);

CREATE INDEX IF NOT EXISTS idx_delivery_outbox_status_ts
ON audience_crm_postgres_outbox (outbox_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_delivery_outbox_run_target
ON audience_crm_postgres_outbox (run_id, delivery_target_id, created_at DESC);
