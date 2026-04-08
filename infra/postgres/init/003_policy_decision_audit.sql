CREATE TABLE IF NOT EXISTS policy_decision_audit (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audience_run(run_id),
    campaign_id TEXT,
    customer_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject')),
    reason_codes TEXT[] NOT NULL DEFAULT '{}'::text[],
    policy_version TEXT NOT NULL,
    fs_version TEXT NOT NULL,
    emb_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    index_alias TEXT NOT NULL,
    index_generation TEXT,
    decision_ts TIMESTAMPTZ NOT NULL,
    decision_explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, customer_id)
);

DROP TRIGGER IF EXISTS trg_policy_decision_audit_no_update_delete ON policy_decision_audit;
CREATE TRIGGER trg_policy_decision_audit_no_update_delete
BEFORE UPDATE OR DELETE ON policy_decision_audit
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();

CREATE INDEX IF NOT EXISTS idx_policy_decision_audit_run_customer
ON policy_decision_audit (run_id, customer_id);

CREATE INDEX IF NOT EXISTS idx_policy_decision_audit_campaign_ts
ON policy_decision_audit (campaign_id, decision_ts DESC);
