# Deployment

This repository provides two Compose stacks:

- `infra/docker-compose.dev.yml` for local development on Docker Desktop.
- `infra/docker-compose.yml` for single-node, prod-shaped deployment.

Both stacks keep Ollama external (`OLLAMA_BASE_URL`) and now use the same custom Airflow image build.

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

- `apache/airflow:3.1.8-python3.11`

Both compose files use the same build strategy:

- image tag: `audience-engine-airflow:3.1.8-python3.11`
- build context: `infra/`
- dockerfile path: `infra/airflow/Dockerfile`

To change Airflow-side Python dependencies, edit `infra/airflow/requirements-airflow.txt`, then rebuild.

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
