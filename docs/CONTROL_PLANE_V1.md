# AudienceEngine Control Plane v1

## Purpose
Define the control plane metadata model for versioning, governance, AI model selection, and audience run lineage.

## Scope Boundary
Control plane and analytics data plane are separate concerns:

| Domain | System of record | What lives here | What does not |
| --- | --- | --- | --- |
| Control plane | Governance registries, operator state, audit tables | Versioned metadata, approvals, entity states, run lineage, lifecycle actions | Raw feature vectors, retrieval payload bodies, model inference outputs |
| Analytics data plane | ClickHouse, Qdrant, runtime pipeline artifacts | Feature snapshots, embeddings, index points, retrieval/ranking execution | Approval workflow, version ownership, promotion decisions |

## Core Entities
AudienceEngine Control Plane v1 uses the following entities.

| Entity | Description | Current source of truth (implemented) | Control Plane v1 expectation |
| --- | --- | --- | --- |
| `FeatureSet` | Logical grouping of governed features for an audience use case | `governance/features/feature_registry.yaml` + feature set files | First-class metadata entity with owner, domain, and status |
| `FeatureSetVersion` | Immutable feature-set contract version (`fs_version`) | `governance/features/feature_sets/*.yaml` | Versioned lifecycle: draft -> validated -> active -> deprecated/retired |
| `Model` | Logical model family (embedding/scoring/explain helper) | Partial, implicit in embedding specs/runtime config | First-class catalog object grouped by capability |
| `ModelVersion` | Immutable version of a model family | Partial, currently represented by `model_version` fields | Explicit version metadata and lifecycle |
| `EmbeddingProvider` | Runtime provider endpoint class (local, AI Hub, future providers) | Implicit local runtime config (`OLLAMA_BASE_URL`) | Cataloged provider with readiness and policy constraints |
| `EmbeddingModelVersion` | Provider-specific embedding model version used in `emb_version` composition | `governance/embeddings/embedding_specs/*.yaml` + runtime model config | Managed model version linked to provider and capability |
| `Policy` | Logical policy family | `governance/policies/policy_registry.yaml` | First-class policy object with owner and scope |
| `PolicyVersion` | Immutable policy version (`policy_version`) | `governance/policies/policy_registry.yaml` | Lifecycle-managed version with validation and approval evidence |
| `AudienceDefinition` | Logical audience intent (business targeting definition) | Partial, implied by campaign/run parameters | First-class reusable definition object |
| `AudienceDefinitionVersion` | Immutable, executable audience definition version | Partial, currently per-run request payload + defaults | Explicit link to `fs_version`, ranking config, policy compatibility |
| `AudienceRun` | Executed audience run with immutable lineage | `audience_run`, `policy_decision_audit`, run summary artifacts | Canonical immutable run record with full bound metadata |
| `DeliveryTarget` | Delivery activation destination type | `governance/delivery/delivery_registry.yaml` | Lifecycle-managed target with readiness state |
| `ExportProfile` | Source+export integration profile | `governance/integrations/integration_registry.yaml` | Managed profile with compatibility constraints |
| `IndexGeneration` / `Alias` / `Promotion` | Versioned retrieval index lifecycle state and alias movements | `index_generations`, `index_lifecycle_audit`, Qdrant alias state | Fully audited promotion/rollback control objects |

## Required Relationships
Minimum required relationships for Control Plane v1:

1. `FeatureSet` 1:N `FeatureSetVersion`
2. `Model` 1:N `ModelVersion`
3. `EmbeddingProvider` 1:N `EmbeddingModelVersion`
4. `EmbeddingModelVersion` N:1 `ModelVersion` (embedding capability)
5. `Policy` 1:N `PolicyVersion`
6. `AudienceDefinition` 1:N `AudienceDefinitionVersion`
7. `AudienceDefinitionVersion` must reference exactly one `FeatureSetVersion`
8. `AudienceDefinitionVersion` must declare compatible `PolicyVersion` set
9. `AudienceRun` must bind one concrete `FeatureSetVersion`, `EmbeddingModelVersion`, `PolicyVersion`, and index alias+generation at execution time
10. `AudienceRun` may use one `ExportProfile` and zero-or-one `DeliveryTarget` per activation flow
11. `Promotion` actions must bind actor identity and point to `IndexGeneration` and `Alias`

## Audience Run Lineage Requirements
Each `AudienceRun` must carry the following lineage envelope at execution time:

| Lineage field | Required now | Present in current runtime/audit |
| --- | --- | --- |
| `run_id` | Yes | Yes |
| `campaign_id` | Yes | Yes |
| `fs_version` | Yes | Yes |
| `emb_version` | Yes | Yes |
| `model_version` | Yes | Yes (present in policy/export audit and expected in run lineage bundle) |
| `policy_version` | Yes | Yes |
| `index_alias` | Yes | Yes |
| `index_generation` (`concrete_qdrant_collection`) | Yes | Yes |
| `integration_profile_id` (`ExportProfile`) | Yes for production runs | Yes (run events/export staging), partial at run-level bundle |
| `delivery_target_id` | Required when delivery stage executes | Yes in delivery audit tables |
| `embedding_provider_id` | Control Plane v1 required | Target-state (not explicit in current run lineage) |
| `audience_definition_version_id` | Control Plane v1 required | Target-state |

## Control Plane Metadata Source of Truth (v1)
Current implementation uses multiple stores; Control Plane v1 keeps that split explicit:

1. Governance registries (`governance/features`, `governance/embeddings`, `governance/policies`, `governance/integrations`, `governance/delivery`) are the source of truth for versioned configuration metadata.
2. Operator defaults (`data/minimal_slice/control_plane/operator_state.json`) are the source of truth for active runtime defaults in the MVP control path.
3. Postgres audit tables are the immutable source of truth for executed run lineage and lifecycle actions.
4. Qdrant alias pointer is the runtime serving pointer, while Postgres lifecycle audit is the control-plane audit source for pointer changes.

## Implemented vs Target-State Notes
Implemented as of 2026-04-10:
- Versioned `fs_version`, `emb_version`, `policy_version` contracts and immutable audit lineage are operational.
- Integration and delivery registries exist with implemented vs planned status.
- Lifecycle actions (`validate/promote/rollback`) are audited with actor identity.

Target-state in Control Plane v1:
- First-class `Model`, `ModelVersion`, `EmbeddingProvider`, `AudienceDefinition`, and `AudienceDefinitionVersion` entities.
- Explicit provider identity in run lineage.
- Unified control-plane metadata API/store abstraction over the current multi-store model.
