# Testing Guide

## Scope
This document defines the required test layout and execution model for Architecture V3 alignment.

## Test Layout
- `tests/contracts/test_governance_contracts.py`
- `tests/unit/test_point_ids.py`
- `tests/unit/test_policy_engine.py`
- `tests/unit/test_version_bundle_preflight.py`
- `tests/integration/test_minimal_slice_smoke.py`

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
- Integration smoke:
  - Compose bring-up.
  - Seed synthetic data.
  - Build generation.
  - Validate generation.
  - Promote alias.
  - Retrieval -> policy -> export.
  - Verify Postgres audit rows exist.

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
