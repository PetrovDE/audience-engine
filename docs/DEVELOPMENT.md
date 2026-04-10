# Development Guide

## Prerequisites
- Python 3.11+
- `uv` (dependency manager and runner): https://docs.astral.sh/uv/
- Docker + Docker Compose (for local infra and integration flows)

## Environment Bootstrap
From repository root:

```bash
make bootstrap
```

This will:
- create `.venv` with Python 3.11
- install runtime groups:
  - `runtime-retrieval-api`
  - `runtime-minimal-slice`
- install dev tools (`pytest`, `ruff`, `mypy`)

## Local Infra Env
- Local compose uses `infra/.env.local` by default via `Makefile`.
- Local Airflow bootstrap credentials are `admin / 203217` (dev-only convenience; not production-safe).
- Local Operator Console login credentials are:
  - `OPERATOR_UI_USERNAME=admin`
  - `OPERATOR_UI_PASSWORD=203217`
- For host-run embedding/retrieval commands, set `OLLAMA_BASE_URL=http://localhost:11434` if needed.
- Retrieval/API RBAC is enabled via API keys in env:
  - `AE_CAMPAIGN_API_KEYS`
  - `AE_ADMIN_API_KEYS`
- Integration MVP connector env settings:
  - ClickHouse source: `CLICKHOUSE_*`, `CLICKHOUSE_FEATURE_SLICE_QUERY`, `CLICKHOUSE_FEATURE_SLICE_LIMIT`
  - Postgres export table: `EXPORT_POSTGRES_*` (defaults can inherit from `POSTGRES_*`)
  - Runtime readiness probe timeout: `INTEGRATION_READINESS_PROBE_TIMEOUT_SECONDS` (seconds)

## Lint and Format
```bash
uv run ruff check .
uv run ruff format .
```

Optional Make targets:

```bash
make lint
make format
```

## Tests
This section moved to the canonical testing guide: `docs/TESTING.md`.

Run tests with `uv`:

```bash
uv run pytest -q tests/unit
uv run pytest -q tests/integration
uv run pytest -q tests/integration/test_clickhouse_postgres_export_e2e.py
```

Optional Make targets:

```bash
make test
make test-integration
```

## CI (GitHub Actions)
Workflows are defined under `.github/workflows`:

- `ci.yml` (required on push/PR to `main`)
  - lint + format check:
    - `make lint`
    - `uv run ruff format --check .`
  - unit tests:
    - `make test-unit`
  - contract tests:
    - `make test-contracts`

- `integration-smoke.yml` (optional)
  - triggers:
    - manual: `workflow_dispatch`
    - nightly: scheduled cron
  - command:
    - `make test-integration-smoke`
  - defaults:
    - CPU-safe path (`SKIP_GPU_TESTS=1`)
    - synthetic data generation in smoke test flow
    - no repository/application secrets required
    - dev `.env` defaults are read from `infra/.env.local`

## Run Services in Dev Mode
Bring local compose stack up/down:

```bash
make dev-up          # core data services
make dev-up-airflow
make dev-up-observability
make dev-up-full
make dev-down
```

Airflow dependencies are now baked into a custom image (`infra/airflow/Dockerfile`) using pinned requirements (`infra/airflow/requirements-airflow.txt`).
Qdrant client/server compatibility is pinned to `1.17.1` and retrieval/index query paths use `query_points` (not deprecated `search`).
When those dependencies change, rebuild the Airflow image with:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml build airflow-api-server
```

Run retrieval API locally:

```bash
uv run --env-file infra/.env.local python -m uvicorn services.retrieval_api.app:app --host 127.0.0.1 --port 8000 --reload
```

Optional Make target:

```bash
make retrieval-api
```

Open the Operator Console at `http://localhost:8000/` and login with `OPERATOR_UI_USERNAME` / `OPERATOR_UI_PASSWORD` from env.

Example calls with role-separated keys:
```bash
curl -H "X-AE-API-Key: campaign_local_key" -H "Content-Type: application/json" \
  -d '{"top_k": 5, "query_customer_id": "cust_00000"}' \
  http://localhost:8000/v1/retrieve

curl -H "X-AE-API-Key: admin_local_key" \
  http://localhost:8000/v1/admin/index/generations/latest

curl -H "X-AE-API-Key: admin_local_key" \
  http://localhost:8000/v1/admin/control-plane/model

curl -H "X-AE-API-Key: admin_local_key" \
  http://localhost:8000/v1/admin/control-plane/integrations

# readiness fields to check in response:
# runtime_runnable, runtime_readiness_mode, runtime_config_valid,
# runtime_connectivity_checked, runtime_connectivity_valid

curl -X POST -H "X-AE-API-Key: admin_local_key" -H "Content-Type: application/json" \
  -d '{"campaign_id":"camp_manual","policy_version":"policy_credit_v1","integration_profile_id":"clickhouse_postgres_export","delivery_target_id":"crm_postgres_outbox","requested_size":20}' \
  http://localhost:8000/v1/admin/runs/trigger

curl -H "X-AE-API-Key: admin_local_key" \
  http://localhost:8000/v1/admin/control-plane/delivery-targets

curl -X POST -H "X-AE-API-Key: admin_local_key" -H "Content-Type: application/json" \
  -d '{"run_id":"<run_uuid>","delivery_target_id":"crm_postgres_outbox"}' \
  http://localhost:8000/v1/admin/delivery/trigger
``` 

Minimal slice demo flow:

```bash
make demo
```

Optional helper targets:

```bash
make seed
make build-index
```

Airflow end-to-end DAG (real minimal-slice chain):
- Primary operator-facing DAG id: `audience_engine_operator_main`
- Legacy internal compatibility DAG id: `audience_engine_minimal_slice_e2e` (manual/internal)
- Defined in: `pipelines/airflow_dags/audience_engine_dags.py`
- API trigger (`POST /v1/admin/runs/trigger`) and Airflow DAG are separate orchestrators that share the same governed runtime modules.
