# AI Hub Integration (Control Plane v1)

## Purpose
Define how AI Hub fits the AudienceEngine control plane for model governance and run lineage.

## Architecture Placement
AI Hub belongs to the control plane model-catalog and provider-governance path, not the analytics data plane.

Execution path summary:
1. Control plane resolves approved provider + model version.
2. Runtime uses that resolved model for embeddings and optional scoring/explain helper tasks.
3. Audience run lineage records exact provider/model identity used.

## Provider Model
Control Plane v1 supports a provider abstraction:

| Provider type | Status | Primary use | Notes |
| --- | --- | --- | --- |
| `local` | Implemented | Embeddings via local Ollama runtime | Current default path in minimal slice |
| `ai_hub` | Target-state | Central model catalog and routed inference | Required for cross-model governance at scale |
| `external` | Target-state | Future managed/provider-specific APIs | Must satisfy same lineage and policy fields |

## Model Catalog Expectations
Model catalog entries must be capability-specific:

| Capability | Required in catalog | Current status |
| --- | --- | --- |
| Embeddings | `model_version`, dimension, provider routing, timeout/batch policy | Partially implemented via embedding specs + runtime config |
| Scoring/Reranking | `model_version`, score semantics, timeout/fallback policy | Target-state |
| Explain/LLM helper (optional) | `model_version`, prompt class, safety constraints, timeout policy | Target-state |

## Required Metadata per Model Version
Each model version must include at least:

| Field | Required | Purpose |
| --- | --- | --- |
| `model_id` | Yes | Logical model family identifier |
| `model_version` | Yes | Immutable executable version id |
| `provider_type` | Yes | `local`, `ai_hub`, or `external` |
| `provider_model_ref` | Yes | Provider-specific model handle |
| `capability` | Yes | `embedding`, `rerank`, `explain_helper` |
| `status` | Yes | Lifecycle state (`draft`, `validated`, `active`, `deprecated`, `retired`) |
| `input_contract_ref` | Yes | Contract for allowed inputs/features |
| `output_contract_ref` | Yes | Contract for output schema (vector/score/text) |
| `timeout_ms` | Yes | Default request timeout |
| `max_batch_size` | Yes for embedding/rerank | Runtime safety and throughput control |
| `pii_policy` | Yes | Explicit policy; default must be no-PII |
| `owner_role` | Yes | Responsible control-plane owner |
| `effective_from` | Yes | Activation timestamp |
| `deprecation_after` | Optional | Planned sunset timestamp |

## Timeout, Failure, and Fallback Expectations

| Capability | Timeout default | Failure mode | Fallback policy |
| --- | --- | --- | --- |
| Embeddings | Strict (`timeout_ms` required) | Fail closed for run stages requiring fresh embeddings | Allowed only to pre-approved model versions in same capability class |
| Scoring/Reranking | Strict for online paths | Degrade to deterministic baseline ranking only if explicitly approved | No implicit provider switch |
| Explain helper | Bounded and non-blocking | Continue run without explain text enrichment | Optional fallback to static reason templates |

Control principle:
- No silent fallback to unapproved models.
- Every fallback path must be pre-registered in control-plane metadata.

## Lineage Requirements for AI Hub Identity
When AI Hub or any provider-based model routing is used, audience-run lineage must include:

1. `provider_type`
2. `provider_id` (or routed endpoint identity)
3. `model_id`
4. `model_version`
5. `capability`
6. `resolved_request_id` (provider request correlation id when available)

Minimum compatibility rule:
- Existing `VersionBundle` fields (`emb_version`, `model_version`) remain mandatory.
- Control Plane v1 extends lineage with explicit provider identity fields.

## Implemented vs Target-State Notes
Implemented as of 2026-04-10:
- Local embedding path is operational with `model_version` lineage fields in audit tables.
- Embedding spec contracts and preflight checks enforce `emb_version` composition and compatibility.

Target-state for AI Hub integration:
- AI Hub-backed model catalog as a first-class provider.
- Provider-aware routing for embeddings, reranking, and optional explain helper tasks.
- Unified model metadata registry with explicit fallback chains and provider readiness checks.
