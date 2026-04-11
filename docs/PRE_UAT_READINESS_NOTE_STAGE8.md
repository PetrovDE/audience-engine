# Stage 8 Pre-UAT Readiness Note

Date: 2026-04-11

## Scope
This note covers pre-UAT stabilization only:
- full verification pass
- role-journey simulation
- small/medium readiness fixes
- compact reset/bootstrap and readiness reporting

## Verified Now (Executed)
- Operator UI host-run startup works with env-loaded credentials.
- Operator login flow works (`/operator/login` -> dashboard redirect).
- Main operator navigation/discoverability works for:
  - dashboard
  - defaults
  - trigger run
  - recent runs
  - delivery
  - explain/audit
  - readiness
  - control-plane versions
- Control-plane version visibility works, including `embedding_model_versions`.
- Governance/evidence flow works (evidence submit + visibility in detail page).
- Trigger Run happy path was executed successfully in runtime and produced a `run_id`.
- Recent Runs, Delivery, Explain/Audit, and Readiness surfaces were exercised with runtime data.
- Provider/model metadata visibility was validated in runtime control-plane output.

## Stabilization Changes in This Stage
- Stabilized DB-backed policy explain integration test startup by adding an explicit Postgres readiness wait after compose bring-up.
- Added compact Stage 8 operator/developer docs pack for reset/bootstrap, verification evidence, and readiness status.

## Intentionally Out of Scope
- Persona-specific RBAC and approval-workflow routing.
- Major UI redesign or broad runtime architecture refactors.
- Production deployment hardening and non-UAT platform expansion.

## Known Non-Blocking Issues
- On this Windows host, `make` is unavailable; use equivalent `docker compose` and `uv` commands directly.
- Full `tests/integration` includes a CPU smoke path that assumes MinIO is reachable; bring MinIO up first when needed:
  - `docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml up -d minio`

## What Still Blocks Real User Rollout
- Persona-isolated authorization and workflow-level approval controls are still target-state.
- This stage is suitable for controlled internal pre-UAT sessions, not open multi-role production rollout.

## Stage 8 Verdict
Pre-UAT readiness is **acceptable for controlled internal testing** with documented caveats and known limits above.
