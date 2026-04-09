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
- `model_version` (runtime embedding model identifier)
- `policy_version`
- `index_alias`
- `concrete_qdrant_collection` (index generation target)
- `run_id` (UUID for immutable run lineage)
- `campaign_id` (string/UUID campaign context)

## VersionBundle Contract
Runtime pipelines and services must exchange a single `VersionBundle` object containing:
- `fs_version`
- `emb_version`
- `model_version`
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
3. Embedding spec `composition.prompt_version` must match runtime prompt id.
4. Embedding spec `composition.model_version` must match runtime embedding model config.
5. Bundle `emb_version` must exactly match `fs_version + prompt_version + model_version`.
6. Bundle `policy_version` is not present in `governance/policies/policy_registry.yaml`.
7. Any PII-tagged feature (`pii != none` in `feature_registry`) would be embedded or logged.

Additionally, minimal-slice runtime validates the full produced embeddings artifact before index build/export:
- every row must contain `emb_version`,
- all rows must have the same `emb_version`,
- the artifact `emb_version` must equal the preflighted `VersionBundle` `emb_version`.

## Deterministic Qdrant Point IDs
- Qdrant point IDs must be deterministic across runs and processes.
- Runtime must not use Python `hash(...)` for persisted point IDs.
- Canonical method: `sha256(customer_id)` first 8 bytes, interpreted as big-endian integer, masked to positive 63-bit.
- This keeps numeric point IDs stable for upsert/idempotency and avoids process-randomized hash behavior.
- Collision risk is low for operational scales, but collision checks should remain in test coverage.

## File Map
- `governance/features/feature_registry.yaml`: canonical feature metadata, PII classification, embedding allowlist flags.
- `governance/features/feature_sets/fs_credit_v1.yaml`: governed feature set for baseline credit audiences.
- `governance/embeddings/embedding_specs/emb_llm_v1.yaml`: historical embedding contract (model_version=`text-embedding-3-large`).
- `governance/embeddings/embedding_specs/emb_llm_v2.yaml`: active embedding contract for minimal slice runtime (model_version=`nomic-embed-text`).
- `governance/policies/policy_registry.yaml`: versioned policy definitions and reason-code bindings.
- `governance/contracts/raw.yaml`: raw ingestion schema contract.
- `governance/contracts/feature_mart.yaml`: transformed feature mart schema contract.
- `governance/dictionaries/reason_codes.yaml`: versioned policy outcome reason-code dictionary (single-registry with changelog entries per semantic change).
- `governance/integrations/integration_registry.yaml`: operational integration catalog (source connectors, export targets, integration profiles with implemented vs planned status).
- `governance/delivery/delivery_registry.yaml`: governed delivery-target catalog (implemented CRM handoff targets vs planned direct API targets).

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
