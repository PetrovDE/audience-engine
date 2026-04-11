# Deployment

This repository provides two Compose stacks:

- `infra/docker-compose.dev.yml` for local development on Docker Desktop.
- `infra/docker-compose.yml` for single-node, prod-shaped deployment.

Both stacks keep Ollama external (`OLLAMA_BASE_URL`) and now use the same custom Airflow image build.
Both stacks now also include API-key RBAC inputs for retrieval/admin role separation.

## Stage 12A) RedOS Host-Run App + Containerized Infra

This stage standardizes deployment as:

- infra services in Docker Compose (`infra/docker-compose.yml`)
- AudienceEngine app on the host as a systemd service on RedOS

Artifacts added for this shape:

- systemd unit: `infra/systemd/audience-engine.service`
- host app env template: `infra/systemd/audience-engine.host.env.example`

Host-run networking rule (important):

- Compose DNS names like `postgres`, `qdrant`, `redis`, `minio`, and `clickhouse` are container-network names.
- The host-run app process must use host-reachable endpoints (`127.0.0.1`/`localhost` with published ports, or real hostnames/IPs).
- Do not copy container-internal hostnames into `/etc/audience-engine/audience-engine.env`.

Canonical single-node service assumptions for this stage:

- repo checkout path: `/opt/audience-engine`
- service env path: `/etc/audience-engine/audience-engine.env`
- service user/group: `audience-engine`
- `uv` install path for systemd startup: `/usr/local/bin/uv`
- app process command: `/usr/local/bin/uv run python -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port 8000`

Detailed operator steps are in `docs/RUNBOOK.md` (RedOS systemd path section).

## 1) Why `_PIP_ADDITIONAL_REQUIREMENTS` Was Removed

Airflow runtime pip mutation was removed to keep startup deterministic and production-honest.

- No startup-time package installation.
- No hidden dependency drift across restarts.
- Airflow Python dependencies are baked into an image at build time.

## 2) Custom Airflow Image

Source of truth:

- Dockerfile: `infra/airflow/Dockerfile`
- Pinned requirements: `infra/airflow/requirements-airflow.txt`

Base image:

- `apache/airflow:3.2.0-python3.11`

Both compose files use the same build strategy:

- image tag: `audience-engine-airflow:3.2.0-python3.11`
- build context: `infra/`
- dockerfile path: `infra/airflow/Dockerfile`

To change Airflow-side Python dependencies, edit `infra/airflow/requirements-airflow.txt`, then rebuild.

Controlled infra/runtime pins in this pass (2026-04-09):
- Airflow image: `apache/airflow:3.2.0-python3.11`
- Postgres: `postgres:16.13-alpine` (major intentionally held at `16`)
- Redis: `redis:7.4.8-alpine`
- MinIO: `minio/minio:RELEASE.2025-09-07T16-13-09Z-cpuv1`
- ClickHouse: `clickhouse/clickhouse-server:26.3.5.12` (26.3 LTS line)
- Qdrant: `qdrant/qdrant:v1.17.1`
- Prometheus: `prom/prometheus:v3.11.1` (already on 3.11 line)
- Grafana: `grafana/grafana:12.4.2`
- Python client alignment: `qdrant-client==1.17.1` (repo + Airflow requirements)

## 3) Environment Files

### Local bootstrap (tracked)

- File: `infra/.env.local`
- Purpose: local/dev convenience only.
- Bootstrap credentials include:
  - Airflow: `admin / 203217`

This is intentionally not production-safe.

### Prod-shaped template (tracked)

- File: `infra/.env.prod.example`
- Copy to: `infra/.env.prod`
- Replace every secret placeholder before deployment.
- Passwords/secrets are separate per service (no shared universal password).

### Reference template

- `infra/.env.example` remains a generic reference template.

RBAC keys in env files:
- `AE_CAMPAIGN_API_KEYS`: comma-separated keys for campaign-user retrieval access.
- `AE_ADMIN_API_KEYS`: comma-separated keys for admin/operator lifecycle + audit APIs.
- If both are unset, protected API routes fail closed (health endpoint remains open).

Connector-specific runtime settings in env files:
- ClickHouse source connector:
  - `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_DB`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`
  - `CLICKHOUSE_FEATURE_SLICE_QUERY`, `CLICKHOUSE_FEATURE_SLICE_LIMIT`
- Postgres export-table connector:
  - `EXPORT_POSTGRES_HOST`, `EXPORT_POSTGRES_PORT`, `EXPORT_POSTGRES_DB`
  - `EXPORT_POSTGRES_USER`, `EXPORT_POSTGRES_PASSWORD`
  - `EXPORT_POSTGRES_SCHEMA`, `EXPORT_POSTGRES_TABLE`, `EXPORT_POSTGRES_SSLMODE`
  - Compose defaults use `EXPORT_POSTGRES_HOST=postgres`; host-run local scripts can override to `localhost`.
- Runtime readiness probe timeout:
  - `INTEGRATION_READINESS_PROBE_TIMEOUT_SECONDS` (default `2.0`)
  - Used by control-plane runtime readiness checks for connectivity-probed connectors.

Reference SQL for the ClickHouse source table contract:
- `infra/clickhouse/sql/001_feature_mart_snapshot.sql`

Operator control-plane runtime state:
- Operator defaults file: `data/minimal_slice/control_plane/operator_state.json`
- Run events log: `data/minimal_slice/control_plane/run_events.jsonl`
- Persist this path with your application data volume strategy if you need continuity of operator defaults and recent-run history.

## 4) Development Workflow

Start core services:

```bash
make dev-up
```

Start core + Airflow:

```bash
make dev-up-airflow
```

Start core + observability:

```bash
make dev-up-observability
```

Start full local stack:

```bash
make dev-up-full
```

Stop local stack:

```bash
make dev-down
```

Local make targets now default to `infra/.env.local`.

## 5) Prod-Shaped Workflow

1. Create runtime env file:

```bash
cp infra/.env.prod.example infra/.env.prod
```

2. Replace all placeholder secrets in `infra/.env.prod`.

3. Start stack:

```bash
make prod-up
```

4. Stop stack:

```bash
make prod-down
```

Prod make targets read `infra/.env.prod`.

## 6) Airflow 3 Topology (Retained)

The Airflow 3 split is unchanged:

- `airflow-init`
- `airflow-api-server`
- `airflow-scheduler`
- `airflow-dag-processor`
- `airflow-triggerer`

Primary operator DAG:
- `audience_engine_operator_main`

Legacy internal compatibility DAG:
- `audience_engine_minimal_slice_e2e` (internal/manual compatibility path)

Operational orchestration note:
- API trigger (`POST /v1/admin/runs/trigger`) and Airflow DAG execution are separate orchestrators over shared governed runtime modules.

## 7) Build and Validation Commands

Build custom Airflow image for dev stack:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml build airflow-api-server
```

Build custom Airflow image for prod-shaped stack:

```bash
docker compose --env-file infra/.env.prod -f infra/docker-compose.yml build airflow-api-server
```

Compose config validation:

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml config
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml --profile airflow --profile observability config
docker compose --env-file infra/.env.prod -f infra/docker-compose.yml config
```

## 8) External Ollama

Ollama remains outside compose.

- Container-side default: `http://host.docker.internal:11434` (local Docker Desktop)
- Host-side default for local scripts: `http://localhost:11434`

Adjust `OLLAMA_BASE_URL` in env files if your Ollama host differs.
