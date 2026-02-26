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
