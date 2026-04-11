# Stage 8 Pre-UAT Reset and Bootstrap Pack

Date: 2026-04-11

## Purpose
Provide a reproducible, operator/developer-safe reset path for a clean internal UAT session.

## 1) Environment Prep
- Required env file: `infra/.env.local`
- Local operator UI credentials come from env:
  - `OPERATOR_UI_USERNAME`
  - `OPERATOR_UI_PASSWORD`
- Local defaults usually resolve to `admin / 203217` for dev-only use.

## 2) Clean Reset (Dev)
From repo root:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml down -v
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml up -d
```

Notes:
- This resets local service state/volumes. Do not use in shared/prod-like environments.
- On Windows hosts without `make`, use the direct `docker compose` commands above.

## 3) Schema and Migration Guidance
New volumes run init SQL automatically. For existing volumes, apply required migrations manually in Postgres:

- `infra/postgres/migrations/001_audit_sink.sql`
- `infra/postgres/migrations/003_policy_decision_audit.sql`
- `infra/postgres/migrations/004_index_lifecycle_audit.sql`
- `infra/postgres/migrations/005_export_staging.sql`
- `infra/postgres/migrations/006_delivery_layer.sql`
- `infra/postgres/migrations/007_delivery_status_no_source_rows.sql`
- `infra/postgres/migrations/008_control_plane_registry_v1.sql`

Example execution pattern:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec -T postgres \
  psql -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
  -f infra/postgres/migrations/008_control_plane_registry_v1.sql
```

## 4) Control-Plane Bootstrap
Seed minimum active registry entries for local/dev test:

```bash
uv run --env-file infra/.env.local python -m pipelines.minimal_slice.control_plane_registry --bootstrap-dev-test
```

Dry run:

```bash
uv run --env-file infra/.env.local python -m pipelines.minimal_slice.control_plane_registry --bootstrap-dev-test --dry-run
```

## 5) Start Host-Run API/UI
```bash
uv run --env-file infra/.env.local python -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port 8000 --reload
```

Open:
- `http://localhost:8000/`
- Login with `OPERATOR_UI_USERNAME` / `OPERATOR_UI_PASSWORD`

## 6) Assumed Defaults/Seeds for UAT
- At least one implemented integration profile is runnable.
- At least one implemented delivery target is runnable.
- Control-plane bootstrap created active versions for:
  - feature set
  - model
  - embedding model/provider
  - policy
  - audience definition

## 7) Known Caveats
- Operator UI is shared-login guidance (not persona-isolated RBAC).
- Planned profiles/targets remain visible but intentionally non-runnable/non-selectable.
- Full smoke integration tests may require extra services (for example MinIO) beyond Postgres/Qdrant-only bring-up.
