# Gap Report: Architecture vs Repository

Date: 2026-02-26
Scope: Compare current repository implementation against `docs/ARCHITECTURE_V3.md` non-negotiable constraints and required platform components.

## 1) Requirement-by-Requirement Status

### GPU required, LangChain embeddings, Qdrant default, blue/green alias
- GPU required: Partial
  - Evidence: `infra/docker-compose.yml` and `infra/docker-compose.dev.yml` define NVIDIA GPU reservation for `ollama`.
  - Gap: No runtime startup guard or pipeline preflight that fails when GPU is unavailable.
- LangChain embeddings: Implemented
  - Evidence: `pipelines/minimal_slice/embedding.py` uses `langchain_ollama.OllamaEmbeddings`.
- Qdrant default: Implemented
  - Evidence: `pipelines/minimal_slice/config.py` and retrieval/index modules use Qdrant URL + alias.
- Blue/green alias lifecycle: Partial
  - Evidence: alias switch exists in `pipelines/minimal_slice/qdrant_index.py`.
  - Gap: only blue collection path exists (`audience-credit-v1-blue`); no explicit green generation lifecycle, validation stage gates, or rollback playbook in code.

### Mandatory policy-engine gate before export
- Status: Partial
  - Evidence: `pipelines/minimal_slice/run_flow.py` executes `evaluate_policy(...)` before `export_approved(...)`.
  - Gap: runtime policy checks do not fully reflect `governance/policies/policy_registry.yaml` rules (e.g., employee suppression, tenure, delinquency); current logic uses blacklist + frequency cap only.

### Governance registries and versioning (`fs_version`, `emb_version`, `policy_version`)
- Status: Partial
  - Evidence: registries/specs exist in `governance/features`, `governance/embeddings`, `governance/policies`; embeddings carry `emb_version` in `pipelines/minimal_slice/embedding.py`.
  - Gaps:
    - run summary audit in `pipelines/minimal_slice/run_flow.py` omits `emb_version`.
    - no strict registry-driven runtime validation that feature/embedding/policy versions align across pipeline stages.
    - no enforced immutable version bump/changelog workflow in code/CI.

### Audit logging for audience runs with versions
- Status: Partial
  - Evidence: `run_summary.json` is written in `pipelines/minimal_slice/run_flow.py`.
  - Gaps:
    - file-based local artifact only; no immutable append-only audit sink.
    - missing complete version bundle in run-level audit (`emb_version` absent).
    - no explicit campaign/run identifiers persisted for lineage across systems.

### ClickHouse/MinIO/Postgres/Redis/Airflow/Observability presence
- Status: Present in infra, mostly not integrated in runtime slice
  - Evidence: `infra/docker-compose.yml` and `infra/docker-compose.dev.yml` include all required services.
  - Gap: minimal slice runtime does not yet persist operational data into ClickHouse/Postgres/MinIO/Redis paths; observability exists via Prometheus/Grafana but coverage is partial.

## 2) Missing Components / Files

- Missing durable audit subsystem artifacts:
  - no dedicated audit schema/module for audience run lineage persistence (DB or object-store backed).
- Missing policy registry executor:
  - no component that loads `governance/policies/policy_registry.yaml` and executes rules directly.
- Missing index lifecycle control artifacts:
  - no explicit index generation manager for blue/green promotion/rollback with retained prior generation metadata.
- Missing scale validation artifacts:
  - no 10M-scale benchmark harness/results committed (load profile, latency/throughput SLO evidence).

## 3) Incomplete Implementations

- `pipelines/minimal_slice/qdrant_index.py`
  - `recreate_collection` on single blue collection is destructive and not a full blue/green lifecycle.
  - point IDs use Python `hash(...)`, which is process-randomized and collision-prone for stable long-lived IDs.
- `pipelines/minimal_slice/retrieval.py`
  - no payload index creation strategy for high-cardinality filters.
  - no query-side policy-aware filtering at retrieval stage.
- `pipelines/minimal_slice/policy_engine.py`
  - static logic does not consume policy registry rules end-to-end.
- `pipelines/minimal_slice/run_flow.py`
  - run audit summary missing full required version references.

## 4) 10M-Scale Risk Assessment

- Index lifecycle risk: High
  - destructive collection recreation and single-generation operation can cause downtime/regression risk.
- Query/filter performance risk: High
  - absent payload index strategy for filter keys can degrade latency at large scale.
- ID stability risk: High
  - unstable hash-based point IDs can break idempotency and incremental updates.
- Audit/compliance risk: High
  - non-immutable local JSON audit trail is insufficient for regulated lineage and forensic needs.
- PII control drift risk: Medium-High
  - governance intent exists, but runtime enforcement does not include robust automated checks for template/logging drift.

## 5) What To Fix First (Ordered)

1. Implement immutable audience run audit sink with complete version tuple (`fs_version`, `emb_version`, `policy_version`, index alias + concrete collection/version, run_id, campaign_id).
2. Replace single-blue destructive index flow with explicit blue/green generation manager and tested promote/rollback path.
3. Make policy gate registry-driven by executing `policy_registry.yaml` rules in runtime, and prevent export when policy artifacts/versions are missing.
4. Enforce runtime governance checks for embedding allowlist and no-PII guarantees before embedding and before logging.
5. Add 10M-scale readiness work: batched upserts, stable deterministic point IDs, payload index definitions, and performance test harness with acceptance thresholds.
6. Integrate currently provisioned platform stores (ClickHouse/MinIO/Postgres/Redis) into durable data, audit, and operational paths.
