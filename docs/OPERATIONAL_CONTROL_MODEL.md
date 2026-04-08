# Operational Control Model

## Purpose
This document defines the first operator/admin control plane for Audience Engine.
It clarifies the single operator workflow, the integration setup model, and runtime policy selection.

## Operator-Facing vs Internal Surfaces

### Primary operator-facing pipeline entrypoint
- Airflow DAG: `audience_engine_operator_main`
- Alternative bootstrap API trigger (same runtime path): `POST /v1/admin/runs/trigger`

### Operator-facing DAGs
- `audience_engine_operator_main`

### Internal/technical DAGs
- `audience_engine_minimal_slice_e2e`
- Status: legacy internal compatibility DAG, manual only (`schedule=None`)
- Operators should use `audience_engine_operator_main`.

### Operator/admin API surfaces
- `GET /v1/admin/control-plane/model`
- `GET|PUT /v1/admin/control-plane/defaults`
- `GET /v1/admin/control-plane/integrations`
- `GET /v1/admin/control-plane/policies`
- `POST /v1/admin/runs/trigger`
- `GET /v1/admin/runs/recent`
- `GET /v1/admin/runs/latest-summary`
- `GET /v1/admin/index/*` lifecycle endpoints
- `GET /v1/policy/decisions/{run_id}/{customer_id}`

### System-internal surfaces
- `pipelines.minimal_slice.run_flow.run_minimal_vertical_slice`
- `pipelines.minimal_slice.lifecycle_service`
- `pipelines.minimal_slice.qdrant_index`

## Integration Model

Registry file:
- `governance/integrations/integration_registry.yaml`

Runtime abstraction modules:
- `pipelines/minimal_slice/integrations.py`
- `pipelines/minimal_slice/control_plane.py`

### Implemented source connectors
- `snapshot_jsonl`: local governed snapshot input.
- `clickhouse_feature_slice`: ClickHouse feature slice input.

### Planned source connectors (not implemented)
- `crm_salesforce`
- `acrm_internal`
- `dwh_snowflake`

### Implemented export targets
- `local_jsonl`: local approved audience file.
- `minio_jsonl`: local file + MinIO upload.

### Planned export targets (not implemented)
- `crm_salesforce_audience`

### Integration profiles
- `local_snapshot_local_export` (implemented)
- `clickhouse_minio_export` (implemented)
- `salesforce_future_profile` (planned)

Only `implemented` profiles/connectors can be selected for runtime execution.

## Policy Selection Model

Policy registry:
- `governance/policies/policy_registry.yaml`

Selection model:
1. Operator default policy is stored in `data/minimal_slice/control_plane/operator_state.json`.
2. Run trigger may override policy (`policy_version`) per run.
3. Runtime validates policy existence in governance registry before execution.
4. Selected policy is bound into:
  - VersionBundle (`policy_version`)
  - policy gate execution call
  - run summary (`versions.policy_version`)
  - run events (`data/minimal_slice/control_plane/run_events.jsonl`)
  - Postgres audit (`audience_run.version_bundle`)

## Run Status and Operational Observability

Run-event log:
- `data/minimal_slice/control_plane/run_events.jsonl`
- Contains success/failure status, run id, policy/integration selection, quality status, export status/URI.

Latest summary:
- `data/minimal_slice/run/run_summary.json`

Durable run lineage:
- Postgres `audience_run`, `audience_run_selected`, `audience_run_rejections_summary`, `policy_decision_audit`

## Standard Operator Workflow
1. Inspect control model and defaults (`/v1/admin/control-plane/model`, `/v1/admin/control-plane/defaults`).
2. Inspect integrations (`/v1/admin/control-plane/integrations`) and choose an implemented profile.
3. Inspect policies (`/v1/admin/control-plane/policies`) and select default or per-run override.
4. Trigger main run (`/v1/admin/runs/trigger`) or trigger DAG `audience_engine_operator_main` with equivalent conf.
5. Monitor progress/results via `/v1/admin/runs/latest-summary`, `/v1/admin/runs/recent`, lifecycle APIs, and policy decision lookup.
6. Validate export status (`export.status`, `export.export_uri`) and audit lineage.

## Deferred Items
- Direct CRM/ACRM/DWH production connectors.
- Rich UI control plane (current phase is API-first).
- A/B experimentation and advanced ranking redesign.
