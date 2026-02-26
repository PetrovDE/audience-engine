CREATE TABLE IF NOT EXISTS audience_run (
    run_id UUID PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    run_ts TIMESTAMPTZ NOT NULL,
    version_bundle JSONB NOT NULL,
    parameters JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audience_run_selected (
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    customer_id TEXT NOT NULL,
    final_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 0),
    channel TEXT NOT NULL,
    selected_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, customer_id)
);

CREATE TABLE IF NOT EXISTS audience_run_rejections_summary (
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    reason_code TEXT NOT NULL,
    rejected_count INTEGER NOT NULL CHECK (rejected_count >= 0),
    summary_ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, reason_code)
);

CREATE OR REPLACE FUNCTION forbid_audience_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audience audit tables are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_audience_run_no_update_delete ON audience_run;
CREATE TRIGGER trg_audience_run_no_update_delete
BEFORE UPDATE OR DELETE ON audience_run
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

DROP TRIGGER IF EXISTS trg_audience_run_selected_no_update_delete ON audience_run_selected;
CREATE TRIGGER trg_audience_run_selected_no_update_delete
BEFORE UPDATE OR DELETE ON audience_run_selected
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

DROP TRIGGER IF EXISTS trg_audience_rejections_no_update_delete ON audience_run_rejections_summary;
CREATE TRIGGER trg_audience_rejections_no_update_delete
BEFORE UPDATE OR DELETE ON audience_run_rejections_summary
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

CREATE INDEX IF NOT EXISTS idx_audience_run_campaign_id ON audience_run (campaign_id);
CREATE INDEX IF NOT EXISTS idx_audience_run_product_id ON audience_run (product_id);
CREATE INDEX IF NOT EXISTS idx_audience_run_selected_customer_id
ON audience_run_selected (customer_id);
