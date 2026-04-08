# Deployment

This repository provides two Compose stacks:

- `infra/docker-compose.dev.yml`: local development on Docker Desktop (Windows/Linux/macOS).
- `infra/docker-compose.yml`: single-node, prod-shaped on-prem deployment.

Both stacks use pinned image versions and **do not run Ollama in Compose**.

## 1) Prerequisites

- Docker Engine + Docker Compose v2.
- For pipeline/retrieval paths that generate embeddings, an external Ollama runtime must be running.
- NVIDIA GPU support is still required for embedding workloads; GPU is expected where Ollama runs.

## 2) Environment Contract

1. Copy the template:

```bash
cp infra/.env.example infra/.env
```

2. Set secrets before shared/server usage:

- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `MINIO_SECRET_KEY`
- `AIRFLOW_FERNET_KEY`
- `AIRFLOW_API_AUTH_JWT_SECRET`
- `AIRFLOW_ADMIN_PASSWORD`
- `GRAFANA_ADMIN_PASSWORD`

3. Configure external Ollama endpoint:

- Containerized components default to `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- Host-run commands can use `OLLAMA_BASE_URL=http://localhost:11434`.
- `AIRFLOW_PIP_ADDITIONAL_REQUIREMENTS` is pinned in `.env.example` so Airflow containers can import and run repository DAG code.

## 3) Development Stack (Docker Desktop)

### Service profiles

`docker-compose.dev.yml` keeps startup flexible:

- Core services (default): Postgres, Redis, MinIO, ClickHouse, Qdrant.
- Airflow profile: `airflow-init`, `airflow-api-server`, `airflow-scheduler`, `airflow-dag-processor`, `airflow-triggerer`.
- Observability profile: Prometheus, Grafana.

### Start commands

Minimal core stack:

```bash
make dev-up
```

Core + Airflow:

```bash
make dev-up-airflow
```

Core + observability:

```bash
make dev-up-observability
```

Full local stack:

```bash
make dev-up-full
```

Stop everything:

```bash
make dev-down
```

### Useful local endpoints

- Postgres: `localhost:${POSTGRES_PORT}`
- Redis: `localhost:${REDIS_PORT}`
- MinIO API: `localhost:${MINIO_API_PORT}`
- MinIO Console: `localhost:${MINIO_CONSOLE_PORT}`
- ClickHouse HTTP: `localhost:${CLICKHOUSE_PORT}`
- Qdrant HTTP: `localhost:${QDRANT_PORT}`
- Airflow API/UI: `localhost:${AIRFLOW_PORT}` (when Airflow profile is enabled)
- Prometheus: `localhost:${PROMETHEUS_PORT}` (observability profile)
- Grafana: `localhost:${GRAFANA_PORT}` (observability profile)

## 4) Airflow 3.1.8 Topology

Airflow is modeled with Airflow 3 service boundaries (no Airflow 2 webserver+scheduler shell hack):

- `airflow-init` (one-shot bootstrap): `airflow db migrate` + admin user creation.
- `airflow-api-server`: `airflow api-server`.
- `airflow-scheduler`: `airflow scheduler`.
- `airflow-dag-processor`: `airflow dag-processor`.
- `airflow-triggerer`: `airflow triggerer`.

Airflow uses Postgres metadata storage and LocalExecutor for this single-node setup.
For hardened server deployments, bake these Python dependencies into a custom Airflow image instead of runtime pip installation.

## 5) Prod-Shaped Single-Node Deployment

Bring up:

```bash
make prod-up
```

Stop:

```bash
make prod-down
```

Characteristics of `infra/docker-compose.yml`:

- Exact pinned versions for all services.
- `restart: always` defaults.
- One-shot bootstrap separated (`airflow-init`) from steady-state services.
- Persistent named volumes for all stateful components.
- Ports bound to `127.0.0.1` for safer single-node defaults.
- External Ollama endpoint required (`OLLAMA_BASE_URL`), no bundled Ollama container.

For remote/operator access, place a reverse proxy or SSH tunnel in front of localhost-bound ports.

## 6) External Ollama Usage

Example checks:

From host:

```bash
curl -fsS http://localhost:11434/api/tags
```

From containers (for example Airflow):

```bash
curl -fsS http://host.docker.internal:11434/api/tags
```

If your Ollama host differs, set `OLLAMA_BASE_URL` accordingly in `infra/.env`.

## 7) Migration Notes (from old Compose layout)

- Removed `ollama` service from both compose files.
- Removed `ollamadata` volume.
- Airflow upgraded from `2.10.5` single-container pattern to Airflow `3.1.8` multi-service architecture.
- Replaced legacy Airflow 2 API auth env with Airflow 3 API auth/JWT settings.
- Dev stack now supports partial startup via profiles (`airflow`, `observability`).
- Prod-shaped stack now uses loopback-only published ports and explicit single-node hardening defaults.
