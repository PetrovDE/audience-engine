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
- For host-run embedding/retrieval commands, set `OLLAMA_BASE_URL=http://localhost:11434` if needed.
- Retrieval/API RBAC is enabled via API keys in env:
  - `AE_CAMPAIGN_API_KEYS`
  - `AE_ADMIN_API_KEYS`

## Lint and Format
```bash
make lint
make format
```

## Tests
This section moved to the canonical testing guide: `docs/TESTING.md`.

Unit tests:

```bash
make test
```

Integration tests:

```bash
make test-integration
```

Direct pytest usage via `uv` is also available:

```bash
uv run pytest -q tests/unit
uv run pytest -q tests/integration
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
When those dependencies change, rebuild the Airflow image with:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml build airflow-api-server
```

Run retrieval API locally:

```bash
make retrieval-api
```

Example calls with role-separated keys:
```bash
curl -H "X-AE-API-Key: campaign_local_key" -H "Content-Type: application/json" \
  -d '{"top_k": 5, "query_customer_id": "cust_00000"}' \
  http://localhost:8000/v1/retrieve

curl -H "X-AE-API-Key: admin_local_key" \
  http://localhost:8000/v1/admin/index/generations/latest
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
- DAG id: `audience_engine_minimal_slice_e2e`
- Defined in: `pipelines/airflow_dags/audience_engine_dags.py`
