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

## Lint and Format
```bash
make lint
make format
```

## Tests
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
    - dev `.env` defaults are used (`infra/.env.example` -> `infra/.env` if needed)

## Run Services in Dev Mode
Bring local compose stack up/down:

```bash
make up
make down
```

Run retrieval API locally:

```bash
make retrieval-api
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
