# Architecture V3 (Bootstrap)

## Purpose
This document defines the architecture baseline for Audience Engine V3.
The baseline was established in M0 documentation and remains the source of architectural constraints, boundaries, and version contracts.

## Product Scope
Audience Engine is an open-source Bank Customer Ranking and Similarity Platform.
It supports large-scale retrieval and ranking for campaign audience construction.

## Non-Negotiable Constraints
- GPU-first production runtime (NVIDIA required).
- Embedding pipeline must use LangChain.
- Scale target: at least 10 million customers.
- Default vector database: Qdrant.
- pgvector is allowed only for dev or small-mode.
- Index lifecycle is blue/green with atomic alias switching.
- Policy Engine is mandatory before export in production paths.
- PII must not be embedded or logged.
- Embedding inputs are allowlist-only features.

## High-Level Architecture
- Data Ingestion Layer: collects source customer and behavioral data.
- Feature Pipeline: computes governed features and emits versioned feature sets.
- Embedding Pipeline (LangChain): converts tabular features to governed text and embeddings.
- Vector Index Layer (Qdrant default): stores embeddings and supports similarity retrieval.
- Ranking Layer: applies scoring and ranking logic for campaign objectives.
- Policy Engine Gate: enforces suppressions, eligibility, caps, conflicts, quotas, and reason codes.
- Audience Export Layer: exports only policy-approved audience members.
- Audit and Governance Layer: records immutable version references and run lineage.

## Required Version Contracts
- `fs_version`: Feature Set version.
- `emb_version`: composed from `fs_version + prompt_version + model_version`.
- `policy_version`: policy definition version.
- Audience and campaign run audit records must include:
  - `fs_version`
  - `emb_version`
  - `policy_version`
  - index alias/version

## Data and Control Flow
1. Ingest raw data into curated datasets.
2. Build governed, non-PII feature sets (`fs_version`).
3. Generate embeddings via LangChain using approved text templates and models (`emb_version`).
4. Build new index generation in blue/green mode.
5. Atomically switch serving alias after validation.
6. Retrieve and rank candidate audiences.
7. Enforce Policy Engine as mandatory export gate.
8. Export approved records and write immutable audit logs.

## Security and Governance Baseline
- Allowlist-only embedding features.
- No PII in prompts, embeddings, or logs.
- Immutable registries per version.
- Version bump + changelog required for registry updates.

## Historical M0 Non-Goals
- No service code implementation.
- No infrastructure deployment.
- No schema migration execution.
- No runtime policy execution.

## Open Decisions for M1
- Exact service boundaries and API contracts.
- Batch vs streaming ingestion mode per source domain.
- Ranking model strategy and calibration workflow.
- SLO and performance test harness definitions.
