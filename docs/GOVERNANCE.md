# Governance Pack (M1)

## Purpose
This document defines the governance artifacts introduced in M1.
The pack is documentation and contract oriented only; no runtime services are implemented here.

## Alignment to Architecture V3
- Embedding inputs are allowlist-only.
- PII is excluded from embedding templates and governed feature sets.
- Policy Engine is mandatory before export in production paths.
- Version contracts are explicit and must be carried in run audit lineage.

Required version contracts:
- `fs_version`
- `emb_version` (composed from `fs_version + prompt_version + model_version`)
- `policy_version`
- `index_alias`
- `concrete_qdrant_collection` (index generation target)
- `run_id` (UUID for immutable run lineage)
- `campaign_id` (string/UUID campaign context)

## VersionBundle Contract
Runtime pipelines and services must exchange a single `VersionBundle` object containing:
- `fs_version`
- `emb_version`
- `policy_version`
- `index_alias`
- `concrete_qdrant_collection`
- `run_id`
- `campaign_id`

This bundle is the required lineage envelope for indexing, retrieval context, and run audit output.

## Required Preflight Guards
Before embedding/indexing/export, runtime must fail fast when:
1. Any `VersionBundle` field is missing or invalid (`run_id` must be UUID).
2. Embedding spec `composition.fs_version` does not match bundle `fs_version`.
3. Bundle `policy_version` is not present in `governance/policies/policy_registry.yaml`.
4. Any PII-tagged feature (`pii != none` in `feature_registry`) would be embedded or logged.

## Deterministic Qdrant Point IDs
- Qdrant point IDs must be deterministic across runs and processes.
- Runtime must not use Python `hash(...)` for persisted point IDs.
- Canonical method: `sha256(customer_id)` first 8 bytes, interpreted as big-endian integer, masked to positive 63-bit.
- This keeps numeric point IDs stable for upsert/idempotency and avoids process-randomized hash behavior.
- Collision risk is low for operational scales, but collision checks should remain in test coverage.

## File Map
- `governance/features/feature_registry.yaml`: canonical feature metadata, PII classification, embedding allowlist flags.
- `governance/features/feature_sets/fs_credit_v1.yaml`: governed feature set for baseline credit audiences.
- `governance/embeddings/embedding_specs/emb_llm_v1.yaml`: embedding contract and template constraints.
- `governance/policies/policy_registry.yaml`: versioned policy definitions and reason-code bindings.
- `governance/contracts/raw.yaml`: raw ingestion schema contract.
- `governance/contracts/feature_mart.yaml`: transformed feature mart schema contract.
- `governance/dictionaries/reason_codes.yaml`: policy outcome reason-code dictionary.

## Change Management
- Registries and contracts are immutable by version.
- Any semantic change requires:
  1. New version identifier.
  2. Changelog entry in the owning artifact.
  3. Downstream compatibility review (feature set, embedding spec, policy registry).

## Non-Goals
- No service implementation.
- No schema migration execution.
- No policy runtime execution.
