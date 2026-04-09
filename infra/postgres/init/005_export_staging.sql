CREATE TABLE IF NOT EXISTS audience_export_staging (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    campaign_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approve')),
    final_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    channel TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    fs_version TEXT NOT NULL,
    emb_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    index_alias TEXT NOT NULL,
    index_generation TEXT NOT NULL,
    integration_profile_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    export_target_id TEXT NOT NULL,
    exported_ts TIMESTAMPTZ NOT NULL,
    export_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, customer_id)
);

DROP TRIGGER IF EXISTS trg_audience_export_staging_no_update_delete ON audience_export_staging;
CREATE TRIGGER trg_audience_export_staging_no_update_delete
BEFORE UPDATE OR DELETE ON audience_export_staging
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

CREATE INDEX IF NOT EXISTS idx_audience_export_staging_campaign_ts
ON audience_export_staging (campaign_id, exported_ts DESC);

CREATE INDEX IF NOT EXISTS idx_audience_export_staging_customer
ON audience_export_staging (customer_id);
