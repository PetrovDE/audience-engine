# Testing Guide

## Scope
This document defines the required test layout and execution model for Architecture V3 alignment.

## Test Layout
- `tests/contracts/test_governance_contracts.py`
- `tests/unit/test_point_ids.py`
- `tests/unit/test_policy_engine.py`
- `tests/unit/test_version_bundle_preflight.py`
- `tests/unit/test_delivery_contract_registry.py`
- `tests/unit/test_delivery_csv_target.py`
- `tests/unit/test_delivery_outbox_idempotency.py`
- `tests/unit/test_delivery_runner_execution.py`
- `tests/unit/test_delivery_store_atomic_outbox.py`
- `tests/integration/test_minimal_slice_smoke.py`
- `tests/integration/test_clickhouse_postgres_export_e2e.py`
- `tests/integration/test_retrieval_api_smoke.py`

## Coverage Mapping
- Contracts:
  - Governance YAML integrity and references.
  - Version tuple presence:
    - `fs_version`
    - `emb_version`
    - `policy_version`
    - `index_alias`
  - No-PII enforcement for governed feature sets via `feature_registry` tags.
- Unit:
  - Deterministic Qdrant point IDs.
  - Policy registry execution, reason-code handling, and quota behavior.
  - Version bundle preflight guards.
  - Delivery contract + delivery registry behavior.
  - CRM CSV materialization ordering/schema.
  - CRM CSV immutable job-scoped artifact lineage.
  - Delivery compatibility gating between integration export and delivery target.
  - Delivery zero-source-row honest non-success status (`skipped_no_source_rows`).
  - Postgres outbox idempotent conflict handling.
  - Atomic outbox + delivery-record persistence path.
- Integration smoke:
  - Compose bring-up.
  - Seed synthetic data.
  - Build generation.
  - Validate generation.
  - Promote alias.
  - Retrieval -> policy -> export.
  - Verify Postgres audit rows exist.
  - Verify governed delivery from `audience_export_staging` to `crm_postgres_outbox`.
  - Verify governed delivery from `audience_export_staging` to `crm_csv_file` with retry-safe immutable artifacts.
  - Verify delivery admin endpoints and RBAC behavior.

## CI Modes
- CPU-first by default:
  - Integration smoke uses CPU-friendly deterministic/precomputed embeddings.
  - No GPU required.
- Optional GPU smoke:
  - Controlled by `SKIP_GPU_TESTS`.
  - Default: `SKIP_GPU_TESTS=1` (skip GPU test).
  - Run GPU smoke with `SKIP_GPU_TESTS=0`.

## Commands
- Contracts: `make test-contracts`
- Unit: `make test-unit`
- Integration smoke (CPU default): `make test-integration-smoke`
- Optional GPU smoke: `make test-integration-gpu`
