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
- `model_version`: runtime embedding model identifier used in emb_version composition.
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

## Current Repository Reality (2026-04-08)
This section records implementation status against V3 constraints so architecture intent and repository reality stay aligned.

### Implemented and Present
- LangChain-based embedding path is implemented (`langchain-ollama`).
- Qdrant is the default vector database in runtime code and compose stacks.
- Alias switching exists for serving (`audience-serving` -> active collection).
- A policy check step runs before export in the minimal vertical slice flow.
- Governance registries and contracts exist under `governance/`.
- Integration registry exists (`governance/integrations/integration_registry.yaml`) with implemented vs planned connector/profile status.
- Real integration connectors are runtime-active for:
  - source: `clickhouse_feature_slice` (query executes against ClickHouse)
  - export: `postgres_export_table` (approved audience rows persisted to Postgres staging table)
- API-first operator/admin control-plane endpoints exist in retrieval API (`/v1/admin/control-plane/*`, `/v1/admin/runs/*`).
- Infra presence exists for Postgres, Redis, MinIO, ClickHouse, Qdrant, Airflow, Prometheus, and Grafana.
- Airflow includes an explicit operator-facing DAG (`audience_engine_operator_main`) and a legacy internal compatibility DAG (`audience_engine_minimal_slice_e2e`).

### Partially Implemented / Divergent from V3
- Ollama is now externalized from compose; runtime enforces local GPU preflight when `OLLAMA_BASE_URL` is local, but does not remotely attest GPU state on external Ollama hosts.
- Blue/green lifecycle is incomplete in practice: only a blue collection path is implemented, with no retained green generation strategy.
- Policy Engine behavior does not fully execute `governance/policies/policy_registry.yaml` rules at runtime.
- Audience run audit output (`data/minimal_slice/run/run_summary.json`) is file-based and not immutable; Postgres audit tables are the durable lineage source.
- Version contracts are present in governance files, but registry-driven validation and strict bump/changelog workflow enforcement are not implemented in runtime checks.

### Scale and Governance Implications
- Current minimal slice is a functional bootstrap, not a production-ready 10M-customer architecture.
- Additional work is required for index lifecycle safety, payload filtering/indexing strategy, immutable audit lineage, and PII guardrail enforcement at runtime.
