-- Migration 008: Control Plane Registry v1 and explicit run-lineage bindings.
-- Mirrors infra/postgres/init/008_control_plane_registry_v1.sql.

CREATE TABLE IF NOT EXISTS feature_sets (
    id UUID PRIMARY KEY,
    feature_set_key TEXT NOT NULL UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feature_set_versions (
    id UUID PRIMARY KEY,
    feature_set_id UUID NOT NULL REFERENCES feature_sets(id),
    version TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN ('draft', 'validated', 'active', 'deprecated', 'retired')
    ),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    UNIQUE (feature_set_id, version)
);

CREATE TABLE IF NOT EXISTS models (
    id UUID PRIMARY KEY,
    model_key TEXT NOT NULL UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_versions (
    id UUID PRIMARY KEY,
    model_id UUID NOT NULL REFERENCES models(id),
    version TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN ('draft', 'validated', 'active', 'deprecated', 'retired')
    ),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    UNIQUE (model_id, version)
);

CREATE TABLE IF NOT EXISTS embedding_providers (
    id UUID PRIMARY KEY,
    provider_key TEXT NOT NULL UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS embedding_model_versions (
    id UUID PRIMARY KEY,
    embedding_provider_id UUID NOT NULL REFERENCES embedding_providers(id),
    model_version_id UUID NOT NULL REFERENCES model_versions(id),
    version TEXT NOT NULL,
    provider_model_ref TEXT NOT NULL,
    capability TEXT NOT NULL DEFAULT 'embedding',
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN ('draft', 'validated', 'active', 'deprecated', 'retired')
    ),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    UNIQUE (embedding_provider_id, version)
);

CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY,
    policy_key TEXT NOT NULL UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS policy_versions (
    id UUID PRIMARY KEY,
    policy_id UUID NOT NULL REFERENCES policies(id),
    version TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN ('draft', 'validated', 'active', 'deprecated', 'retired')
    ),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    UNIQUE (policy_id, version)
);

CREATE TABLE IF NOT EXISTS audience_definitions (
    id UUID PRIMARY KEY,
    audience_definition_key TEXT NOT NULL UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audience_definition_versions (
    id UUID PRIMARY KEY,
    audience_definition_id UUID NOT NULL REFERENCES audience_definitions(id),
    feature_set_version_id UUID NOT NULL REFERENCES feature_set_versions(id),
    policy_version_id UUID REFERENCES policy_versions(id),
    version TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN ('draft', 'validated', 'active', 'deprecated', 'retired')
    ),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    UNIQUE (audience_definition_id, version)
);

CREATE TABLE IF NOT EXISTS audience_run_lineage_binding (
    run_id UUID PRIMARY KEY REFERENCES audience_run(run_id),
    feature_set_version_id UUID REFERENCES feature_set_versions(id),
    model_version_id UUID REFERENCES model_versions(id),
    embedding_model_version_id UUID REFERENCES embedding_model_versions(id),
    policy_version_id UUID REFERENCES policy_versions(id),
    audience_definition_version_id UUID REFERENCES audience_definition_versions(id),
    delivery_target_id TEXT,
    export_profile_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_feature_set_versions_active_per_set
ON feature_set_versions (feature_set_id)
WHERE lifecycle_state = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_model_versions_active_per_model
ON model_versions (model_id)
WHERE lifecycle_state = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_embedding_model_versions_active_per_provider
ON embedding_model_versions (embedding_provider_id)
WHERE lifecycle_state = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_versions_active_per_policy
ON policy_versions (policy_id)
WHERE lifecycle_state = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_audience_definition_versions_active_per_definition
ON audience_definition_versions (audience_definition_id)
WHERE lifecycle_state = 'active';

CREATE INDEX IF NOT EXISTS idx_feature_set_versions_state_created
ON feature_set_versions (lifecycle_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_versions_state_created
ON model_versions (lifecycle_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_embedding_model_versions_state_created
ON embedding_model_versions (lifecycle_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_policy_versions_state_created
ON policy_versions (lifecycle_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audience_definition_versions_state_created
ON audience_definition_versions (lifecycle_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audience_run_lineage_policy_version
ON audience_run_lineage_binding (policy_version_id);

DROP TRIGGER IF EXISTS trg_audience_run_lineage_binding_no_update_delete ON audience_run_lineage_binding;
CREATE TRIGGER trg_audience_run_lineage_binding_no_update_delete
BEFORE UPDATE OR DELETE ON audience_run_lineage_binding
FOR EACH ROW EXECUTE FUNCTION forbid_audience_audit_mutation();
