# Build Plan

## Planning Principles
- Build in milestones with explicit Definition of Done (DoD).
- Preserve constitution constraints and governance invariants.
- Prefer OSS components and reproducible local setup.
- Treat policy enforcement and audit lineage as first-class requirements.

## Milestones

### M0: Bootstrap Documentation
Scope:
- Establish architecture baseline.
- Establish repository manifest.
- Establish milestone build plan.
- Establish contributor workflow for Cursor/Codex collaboration.

DoD:
- Required docs exist under `docs/`.
- Constraints and invariants are captured in architecture and workflow docs.
- No service implementation introduced.

### M1: Repository Skeleton and Contracts
Scope:
- Create directory skeleton (`services`, `governance`, `pipelines`, `infra`, `tests`).
- Define initial API and data contracts.
- Add reproducible local config (`docker-compose`, `.env.example`, `Makefile`).

DoD:
- Skeleton committed with lintable placeholder modules.
- Contract docs reviewed and linked from architecture.
- Local bootstrap commands documented and repeatable.

### M2: Governance and Registries
Scope:
- Introduce feature registry and feature set versioning.
- Introduce embedding spec registry (`emb_version` contract).
- Introduce policy registry and reason code dictionary.

DoD:
- Registries are versioned and immutable per version.
- Version bump workflow documented.
- Validation checks for allowlist-only embedding fields defined.

### M3: Embedding and Index Pipeline (GPU-first)
Scope:
- Implement LangChain-based embedding pipeline.
- Build Qdrant-first index lifecycle with blue/green alias switching.
- Add pgvector dev-mode option only.

DoD:
- End-to-end embedding and indexing in non-production environment.
- Alias swap procedure tested.
- Performance baseline produced for sample scale.

### M4: Retrieval, Ranking, and Policy Gate
Scope:
- Implement retrieval and ranking flow.
- Implement mandatory Policy Engine gate before export.
- Emit standardized rejection reasons and audit records.

DoD:
- No export path bypasses Policy Engine.
- Audience runs persist all required version references.
- Functional tests cover suppressions, eligibility, caps, conflicts, and quotas.

### M5: Hardening and Scale Readiness (Current Focus)
Scope:
- Performance, resiliency, and observability hardening.
- Validate operational readiness for at least 10 million customers.
- Complete runbooks and release checklist.

DoD:
- Scale test evidence meets defined thresholds.
- Alerting and dashboards cover critical flows.
- Production readiness review completed.

## Dependency Order
1. M0 before all milestones.
2. M1 contracts before registry and service implementation.
3. M2 registries before M3/M4 runtime logic.
4. M3 index lifecycle before production retrieval.
5. M4 policy gate before any export capability.
6. M5 only after functional completeness.

## Current Status Notes
- M0 through M2 artifacts are present and materially implemented.
- M3 and M4 are functionally bootstrapped in a minimal slice, with notable architectural gaps still open for production-grade compliance.
- M5 is not yet complete; 10M readiness evidence and hardening controls remain outstanding.
- Detailed architecture-vs-repo gaps and remediation order are tracked in `docs/GAP_REPORT_ARCH_VS_REPO.md`.

## Priority Focus (from Gap Analysis)
1. Add immutable run-audit lineage with complete version tuple (`fs_version`, `emb_version`, `policy_version`, index alias/version).
2. Complete blue/green index lifecycle with non-destructive promotion and rollback.
3. Make policy gate runtime registry-driven and mandatory for all export paths.
4. Enforce runtime no-PII/allowlist checks on embedding and logging paths.
5. Deliver 10M scale readiness artifacts (batched indexing, payload index strategy, deterministic IDs, benchmark harness/results).
