# Docs Bundle

This file is the concise, audit-ready single-document summary for Audience Engine.

## What the Platform Is
Audience Engine is an open-source bank customer ranking and similarity platform for campaign audience construction. It combines governed features, embeddings, vector retrieval, ranking, policy gating, and audited export.

## Architecture V3 Summary
- GPU-first production intent with NVIDIA runtime requirements.
- Embeddings use LangChain.
- Qdrant is the default vector database.
- Index lifecycle uses generation build/validate/promote/rollback with alias switching.
- Policy Engine gate is mandatory before export.
- PII must not be embedded or logged.
- Required version lineage includes `fs_version`, `emb_version`, `policy_version`, and index alias/generation context.
- API-key RBAC separates campaign retrieval access from admin lifecycle/audit operations.
- API-first operator/admin control plane now defines one primary operator DAG and run trigger model.
- Runtime data-quality gates validate raw/feature/embedding artifacts in the primary run path.
- Lifecycle validate/promote/rollback operations converge through one audited control path (`lifecycle_service`) for API and system-triggered execution.

Canonical references:
- [ARCHITECTURE_V3.md](ARCHITECTURE_V3.md)
- [OPERATIONAL_CONTROL_MODEL.md](OPERATIONAL_CONTROL_MODEL.md)
- [GAP_REPORT_ARCH_VS_REPO.md](GAP_REPORT_ARCH_VS_REPO.md)

## VersionBundle (fs/emb/policy/index alias + generation)
Version lineage is carried as a single `VersionBundle` object:
- `fs_version`
- `emb_version` (`fs_version + prompt_version + model_version`)
- `model_version`
- `policy_version`
- `index_alias`
- `concrete_qdrant_collection`
- `run_id`
- `campaign_id`

Runtime generation:
- Built in `pipelines/version_bundle.py` via `build_version_bundle(...)`.
- Validated with `preflight_version_bundle(...)` against embedding spec/runtime parity, policy registry, and PII/no-allowlist violations before downstream steps.
- Runtime validates the full generated embeddings artifact: every row must carry `emb_version`, mixed values are rejected, and the artifact `emb_version` must equal the preflighted bundle before index build.
- Active minimal-slice embedding spec: `governance/embeddings/embedding_specs/emb_llm_v2.yaml` (`emb_llm_v1.yaml` retained as historical contract).

Canonical reference:
- [GOVERNANCE.md](GOVERNANCE.md)

## Data Zones and Stores
- Raw synthetic/slice inputs: `data/minimal_slice/run/*.jsonl`.
- Feature mart snapshot: local file plus optional MinIO Parquet mirror.
- Embeddings: local JSONL (`embeddings.jsonl`) for index build.
- Vector index: Qdrant collection(s) behind alias (`audience-serving` default).
- Retrieval/policy intermediate data: in-memory pipeline payloads.
- Export: local `approved_audience.jsonl` plus optional MinIO object upload.
- Audit sink: Postgres append-only tables (`audience_run`, `audience_run_selected`, `audience_run_rejections_summary`).
- Policy decision audit: Postgres append-only table (`policy_decision_audit`) with one row per evaluated customer.
- Optional source/cache stores: ClickHouse (feature slice source), Redis (embedding cache).

Canonical references:
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [RUNBOOK.md](RUNBOOK.md)
- [AUDIT.md](AUDIT.md)

## End-to-End Run Flow
1. Seed: synthetic customer data is generated.
2. Feature mart: governed feature snapshot is built (`fs_version`).
3. Embed: embedding text and vectors are created (`emb_version`).
4. Index: Qdrant collection generation is built and targeted by alias context.
5. Recommend: similarity retrieval generates ranked candidates.
6. Policy: policy checks approve/reject and emit reason codes (`policy_version`).
  - Required policy inputs in minimal slice: `blacklist`, `communication_history`.
  - Missing/unreadable/invalid required input triggers fail-closed rejection with reason code `POLICY_FAIL_CLOSED_REQUIRED_INPUT`.
7. Export: approved audience rows are written to output.
8. Audit: run summary plus Postgres append-only audit records are persisted.
9. Explain/read: retrieval API exposes `GET /v1/policy/decisions/{run_id}/{customer_id}` from audit storage.

Operational control selection during run:
- Policy version is selected from operator defaults or per-run override.
- Integration profile is selected from the integration registry (`governance/integrations/integration_registry.yaml`) and must be marked `implemented`.
- Run events are appended to `data/minimal_slice/control_plane/run_events.jsonl` for recent-run and failure visibility.

Flow command:
```bash
make demo
```

## Operational SOP Highlights
Index promote/rollback:
- Build generation: `make build-index`
- Validate generation: `make validate-index`
- Promote validated generation: `make promote-index`
- Roll back alias if needed: `make rollback-index`

Policy updates:
- Treat `governance/policies/policy_registry.yaml` as versioned/immutable-by-version.
- Bump `policy_version` for semantic changes.
- Keep reason code bindings aligned with `governance/dictionaries/reason_codes.yaml`.
- For semantic reason-code changes, bump dictionary `version` and append a `changelog` entry.

Audit operations:
- Keep audit tables append-only.
- Verify recent version lineage from Postgres:
```sql
SELECT run_id, campaign_id, run_ts, version_bundle->>'emb_version' AS emb_version
FROM audience_run
ORDER BY run_ts DESC
LIMIT 5;
```

Lifecycle operations now have a protected API surface:
- `POST /v1/admin/index/generations/validate-latest`
- `POST /v1/admin/index/alias/promote-latest`
- `POST /v1/admin/index/alias/rollback-latest`
- `GET /v1/admin/index/lifecycle-audit`

Operator control-plane APIs:
- `GET /v1/admin/control-plane/model`
- `GET|PUT /v1/admin/control-plane/defaults`
- `GET /v1/admin/control-plane/integrations`
- `GET /v1/admin/control-plane/policies`
- `POST /v1/admin/runs/trigger`
- `GET /v1/admin/runs/recent`
- `GET /v1/admin/runs/latest-summary`
- Orchestration note: API trigger and Airflow DAG are distinct orchestrators over the same governed runtime modules (they are not a single shared orchestrator function).

System-triggered lifecycle operations remain allowed for trusted internal flows, but they use the same lifecycle service and lifecycle audit sink with explicit actor identities (`system:run_flow`, `system:airflow:<run_id>`, `system:makefile`).

Airflow operational execution:
- Primary operator DAG: `audience_engine_operator_main`
- Legacy internal compatibility DAG: `audience_engine_minimal_slice_e2e`

Canonical references:
- [INDEX_LIFECYCLE.md](INDEX_LIFECYCLE.md)
- [POLICY_ENGINE_SPEC.md](POLICY_ENGINE_SPEC.md)
- [AUDIT.md](AUDIT.md)
- [OPERATIONAL_CONTROL_MODEL.md](OPERATIONAL_CONTROL_MODEL.md)

## Demo + Smoke Tests and Expected Outputs
Demo run:
```bash
make demo
```

Expected demo outputs:
- `data/minimal_slice/run/run_summary.json` exists and includes:
  - `versions` with full VersionBundle tuple.
  - `retrieval.retrieved_count`
  - `policy` summary counts.
  - `export_path` value.
- `data/minimal_slice/run/approved_audience.jsonl` exists.
- Postgres has rows in:
  - `audience_run`
  - `audience_run_selected`
  - `audience_run_rejections_summary`
  - `policy_decision_audit`

Smoke tests:
```bash
make test-integration-smoke
make test-integration-gpu   # optional; requires SKIP_GPU_TESTS=0
```

Expected smoke behavior:
- CPU smoke path runs without GPU (`SKIP_GPU_TESTS=1` default) using deterministic mock embeddings.
- GPU smoke path runs full minimal slice when enabled.

Canonical reference:
- [TESTING.md](TESTING.md)
