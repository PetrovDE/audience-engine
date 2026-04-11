# Operations Runbook

This document adds operational guidance for the Postgres audit sink.
For monitoring dashboards and metrics triage, see the root runbook: `../RUNBOOK.md`.
Index generation lifecycle SOP moved to `docs/INDEX_LIFECYCLE.md`.
Deployment model and artifacts are documented in `docs/DEPLOYMENT.md`.

## RedOS Host-Service Deployment (Stage 12A)

This section is the canonical path for single-node server deployment where:

- infra runs in Docker Compose
- AudienceEngine API runs on the host via systemd

### Prerequisites

Required on the RedOS host:

- Docker Engine + Docker Compose v2 (`docker compose`)
- Python 3.11+
- `curl`
- `git` (or another way to place repo files at `/opt/audience-engine`)
- systemd (default on RedOS)

Quick checks:

```bash
docker --version
docker compose version
python3 --version
```

### Host Layout and Service User

Use this layout:

- project root: `/opt/audience-engine`
- service env file: `/etc/audience-engine/audience-engine.env`
- systemd unit: `/etc/systemd/system/audience-engine.service`
- runtime writable data: `/opt/audience-engine/data/minimal_slice/*`

Create service user and directories:

```bash
sudo useradd --system --create-home --home-dir /home/audience-engine --shell /sbin/nologin audience-engine || true
sudo install -d -m 0750 -o audience-engine -g audience-engine /etc/audience-engine
sudo install -d -m 0750 -o audience-engine -g audience-engine /opt/audience-engine/data/minimal_slice/run
sudo install -d -m 0750 -o audience-engine -g audience-engine /opt/audience-engine/data/minimal_slice/delivery
sudo install -d -m 0750 -o audience-engine -g audience-engine /opt/audience-engine/data/minimal_slice/control_plane
```

### Project Checkout and uv Setup

Checkout code:

```bash
sudo mkdir -p /opt/audience-engine
sudo chown "$USER":"$USER" /opt/audience-engine
git clone <YOUR_REPO_URL> /opt/audience-engine
cd /opt/audience-engine
```

Install `uv` only if missing:

```bash
if [ ! -x /usr/local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
fi
```

Validate `uv` for service startup path:

```bash
/usr/local/bin/uv --version
sudo -u audience-engine /usr/local/bin/uv --version
```

Create environment and install runtime dependencies:

```bash
cd /opt/audience-engine
sudo -u audience-engine bash -lc 'cd /opt/audience-engine && /usr/local/bin/uv venv .venv --python 3.11'
sudo -u audience-engine bash -lc "cd /opt/audience-engine && /usr/local/bin/uv sync --group runtime-retrieval-api --group runtime-minimal-slice --locked"
```

### Configure Env Files

Compose infra env:

```bash
cd /opt/audience-engine
cp infra/.env.prod.example infra/.env.prod
```

Host app env (systemd EnvironmentFile):

```bash
sudo cp infra/systemd/audience-engine.host.env.example /etc/audience-engine/audience-engine.env
sudo chown audience-engine:audience-engine /etc/audience-engine/audience-engine.env
sudo chmod 0640 /etc/audience-engine/audience-engine.env
```

Edit both files and replace placeholders before start.

Host-run vs container-network rule:

- In `/etc/audience-engine/audience-engine.env`, use host-reachable endpoints (`127.0.0.1`/`localhost` or real host/IP).
- Do not use compose-internal names (`postgres`, `qdrant`, `redis`, `minio`, `clickhouse`) in that host env file.
- Compose-internal names are valid only for container-to-container traffic.

### Bring Up Infra Containers

Start infra:

```bash
cd /opt/audience-engine
docker compose --env-file infra/.env.prod -f infra/docker-compose.yml up -d
```

Verify container state:

```bash
docker compose --env-file infra/.env.prod -f infra/docker-compose.yml ps
```

Verify key service reachability from host:

```bash
curl -fsS http://127.0.0.1:6333/healthz
curl -fsS http://127.0.0.1:8123/ping
docker compose --env-file infra/.env.prod -f infra/docker-compose.yml exec redis redis-cli ping
```

### Install and Start systemd Service

Install service unit from repo artifact:

```bash
cd /opt/audience-engine
sudo cp infra/systemd/audience-engine.service /etc/systemd/system/audience-engine.service
sudo systemctl daemon-reload
sudo systemctl enable --now audience-engine.service
```

Validate the exact startup command path used by systemd:

```bash
sudo systemctl cat audience-engine.service
sudo -u audience-engine bash -lc 'cd /opt/audience-engine && /usr/local/bin/uv run python -c "import uvicorn; print(\"uv_startup_path_ok\")"'
```

Unit ordering assumptions in this deployment shape:

- service starts after `network-online.target` and `docker.service`
- service has `Wants=docker.service` but does not start compose services automatically
- operators must bring infra up (`docker compose ... up -d`) before starting or enabling the app service

Operational commands:

```bash
sudo systemctl start audience-engine.service
sudo systemctl stop audience-engine.service
sudo systemctl restart audience-engine.service
sudo systemctl status audience-engine.service
sudo journalctl -u audience-engine.service -n 200 --no-pager
sudo journalctl -u audience-engine.service -f
```

### Bootstrap and Schema Notes

For a fresh Postgres volume, schema init SQL is applied automatically by compose.

Optional initial bootstrap tasks:

```bash
sudo -u audience-engine bash -lc 'cd /opt/audience-engine && /usr/local/bin/uv run --env-file /etc/audience-engine/audience-engine.env python -m pipelines.minimal_slice.control_plane_registry --bootstrap-dev-test'
sudo -u audience-engine bash -lc 'cd /opt/audience-engine && /usr/local/bin/uv run --env-file /etc/audience-engine/audience-engine.env python -m pipelines.minimal_slice.user_admin --bootstrap-dev-admin'
```

For an existing Postgres volume, apply SQL migrations from `infra/postgres/migrations` before relying on new control-plane or delivery paths.

### Common Failures and Checks

1. Service restarts repeatedly (`systemctl status` shows failed).
   - Check `journalctl -u audience-engine.service`.
   - Confirm `/etc/audience-engine/audience-engine.env` exists and has readable permissions for `audience-engine`.
   - Confirm `WorkingDirectory=/opt/audience-engine` contains the project checkout.

2. App starts but infra calls fail (connection refused or name resolution errors).
   - Re-check host env values: use `127.0.0.1`/host IP, not compose DNS names.
   - Confirm compose stack is healthy with `docker compose ... ps`.

3. Protected endpoints return RBAC errors.
   - Ensure `AE_CAMPAIGN_API_KEYS` and/or `AE_ADMIN_API_KEYS` are set in `/etc/audience-engine/audience-engine.env`.

4. Operator login fails.
   - Ensure `AE_OPERATOR_SESSION_SECRET` is set.
   - Ensure bootstrap admin exists (run `--bootstrap-dev-admin`) or valid UI fallback creds are configured.

5. Runtime errors related to missing tables.
   - If database volume is not fresh, run pending migrations from `infra/postgres/migrations`.

### Minimal Validation Checklist

1. Service is active:
   ```bash
   sudo systemctl is-active audience-engine.service
   ```
2. Health endpoint responds:
   ```bash
   curl -fsS http://127.0.0.1:8000/healthz
   ```
3. Operator UI login page is reachable:
   - `http://<server-host>:8000/operator/login`
4. Core infra dependencies respond:
   - Qdrant: `curl -fsS http://127.0.0.1:6333/healthz`
   - ClickHouse: `curl -fsS http://127.0.0.1:8123/ping`
   - Redis: `docker compose --env-file infra/.env.prod -f infra/docker-compose.yml exec redis redis-cli ping`
5. Trigger-run smoke path succeeds with admin API key:
   ```bash
   curl -fsS -X POST "http://127.0.0.1:8000/v1/admin/runs/trigger" \
     -H "X-AE-API-Key: <admin_api_key>" \
     -H "Content-Type: application/json" \
     -d '{"campaign_id":"stage12a_smoke","policy_version":"policy_credit_v1","requested_size":20}'
   ```

## Operator Workflow (Primary)
Use this sequence for operational usage.

Canonical local API/UI startup from repo root:
```bash
uv run --env-file infra/.env.local python -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port 8000 --reload
```
This `--env-file` load is required so Operator Console credentials are read from `infra/.env.local`.

1. Open the operator UI in browser:
   ```text
   http://localhost:8000/
   ```
2. Login with Operator Console credentials from env:
   - `OPERATOR_UI_USERNAME`
   - `OPERATOR_UI_PASSWORD`
   - local bootstrap default: `admin / 203217` (dev-only)
3. Use **Dashboard** and **Integrations / Readiness** to inspect:
   - integration readiness
   - delivery target readiness
   - selected defaults
   - main Airflow DAG id (`audience_engine_operator_main`) and usage hints
4. Use **Defaults** to update:
   - `default_policy_version`
   - `default_integration_profile_id`
   - `default_delivery_target_id`
5. Use **Trigger Run** to launch a run with:
   - `campaign_id` (required)
   - optional overrides for policy/profile/delivery
   - `requested_size`
6. Use **Recent Runs** and **Delivery** to monitor:
   - run status and selected lineage controls
   - delivery jobs/attempts by run id or recent stream
   - rows attempted/written/skipped-conflict where available
7. Use **Explain / Audit** for:
   - policy decision explain lookup (`run_id + customer_id`)
   - lifecycle audit summary
   - delivery attempt audit summary

Readiness interpretation:
- `runtime_runnable=true` is the operator-safe gate.
- `runtime_readiness_mode=config_and_connectivity` means config + probe both succeeded.
- `runtime_readiness_mode=config_only` means config validation passed and no probe is required.
- `runtime_readiness_mode=not_implemented` remains visible for roadmap honesty and is non-selectable in defaults/run-trigger forms.

API/DAG-only notes (still implemented and supported):
- Index lifecycle mutate operations (`validate/promote/rollback`) are API/system-path operations, not UI actions.
- Direct delivery trigger endpoint (`POST /v1/admin/delivery/trigger`) remains API-driven.
- Airflow-triggered runs and API/UI-triggered runs are separate orchestrators over shared governed runtime modules.

## Audit Sink Bring-up
1. Start infra:
   ```bash
   make dev-up
   ```
2. Ensure Postgres init SQL ran (new volumes only):
   ```bash
   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec postgres \
     psql -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     -c "\dt audience_run*"
   ```
3. Run minimal slice:
   ```bash
   uv run --env-file infra/.env.local python -m pipelines.minimal_slice.run_flow
   ```

## Durable Data Paths (MinIO / ClickHouse / Redis)
Use these runtime controls when operating the minimal slice with provisioned stores:

- `FEATURE_SLICE_SOURCE=snapshot`: build feature mart from local synthetic snapshot input.
- `FEATURE_SLICE_SOURCE=clickhouse`: read minimal governed slice from ClickHouse query (`CLICKHOUSE_FEATURE_SLICE_QUERY`).
- ClickHouse source contract reference SQL: `infra/clickhouse/sql/001_feature_mart_snapshot.sql`.
- Feature mart snapshots are persisted to MinIO as Parquet:
  - `s3://<MINIO_BUCKET>/<MINIO_FEATURE_MART_PREFIX>/fs_version=<...>/run_id=<...>/snapshot.parquet`
- Approved export outputs are uploaded to MinIO using run lineage:
  - `s3://<MINIO_BUCKET>/<MINIO_EXPORT_PREFIX>/run_id=<run_id>/approved_audience.jsonl`
- When integration profile uses `postgres_export_table`, approved rows are also written to:
  - `<EXPORT_POSTGRES_SCHEMA>.<EXPORT_POSTGRES_TABLE>` (default: `public.audience_export_staging`)
- Embedding cache keys are stored in Redis by `emb_version` and text hash:
  - `<REDIS_EMBEDDING_CACHE_PREFIX>:<emb_version>:<sha256>`

## Backup (Logical)
Use `pg_dump` to capture durable audit tables.

```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec postgres \
  pg_dump -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
  --table=audience_run \
  --table=audience_run_selected \
  --table=policy_decision_audit \
  --table=audience_run_rejections_summary \
  --format=custom \
  --file=/tmp/audience_audit.dump
```

Copy backup from container:
```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml cp postgres:/tmp/audience_audit.dump ./audience_audit.dump
```

## Restore
1. Restore into a target DB:
   ```bash
   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml cp ./audience_audit.dump postgres:/tmp/audience_audit.dump
   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec postgres \
     pg_restore -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     --clean --if-exists --no-owner --no-privileges /tmp/audience_audit.dump
   ```
2. Validate row counts:
   ```bash
   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec postgres \
     psql -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     -c "SELECT 'audience_run' AS table, count(*) FROM audience_run
         UNION ALL SELECT 'audience_run_selected', count(*) FROM audience_run_selected
         UNION ALL SELECT 'policy_decision_audit', count(*) FROM policy_decision_audit
         UNION ALL SELECT 'audience_run_rejections_summary', count(*) FROM audience_run_rejections_summary;"
   ```

## Notes
- Init SQL (`infra/postgres/init/001_audit_sink.sql`) runs only on first database initialization (empty `pgdata` volume).
- For existing environments, apply migrations manually:
  - `infra/postgres/migrations/001_audit_sink.sql`
  - `infra/postgres/migrations/003_policy_decision_audit.sql`
  - `infra/postgres/migrations/005_export_staging.sql`
  - `infra/postgres/migrations/006_delivery_layer.sql`
  - `infra/postgres/migrations/007_delivery_status_no_source_rows.sql`
- Mutation-protected audit tables reject updates/deletes via trigger (`audience_run*`, `policy_decision_audit`, `audience_export_staging`, `audience_delivery_attempt`, `audience_delivery_record`, `audience_crm_postgres_outbox`).
- `audience_delivery_job` is intentionally stateful and updates status through delivery lifecycle stages.
- Policy decision explain endpoint is available at `GET /v1/policy/decisions/{run_id}/{customer_id}` via retrieval API.
- If `FEATURE_SLICE_SOURCE=clickhouse`, ensure `CLICKHOUSE_FEATURE_SLICE_QUERY` returns all contract columns needed by `governance/contracts/feature_mart.yaml`.
- For `clickhouse_postgres_export`, validate export-target settings:
  - `EXPORT_POSTGRES_HOST`, `EXPORT_POSTGRES_PORT`, `EXPORT_POSTGRES_DB`
  - `EXPORT_POSTGRES_USER`, `EXPORT_POSTGRES_PASSWORD`
  - `EXPORT_POSTGRES_SCHEMA`, `EXPORT_POSTGRES_TABLE`
- Delivery registry:
  - `governance/delivery/delivery_registry.yaml`
  - implemented: `crm_csv_file`, `crm_postgres_outbox`
  - planned only: `crm_api_future`, `acrm_api_future`
- Delivery target compatibility:
  - `crm_csv_file` and `crm_postgres_outbox` require integration export targets that write `audience_export_staging` (for example `postgres_export_table`).
- Delivery status model includes non-success no-source visibility:
  - `skipped_no_source_rows`
- Delivery source of truth remains `audience_export_staging`; no direct policy-result bypass is used for delivery.
- Delivery currently supports staged activation only (CSV/outbox handoff). Direct CRM API push targets remain planned, not runtime-implemented.
- If MinIO credentials are unset/invalid, feature-mart Parquet and export uploads fail fast during runtime operations.
- If Redis cache is unavailable, embedding runs fail; disable cache explicitly with `REDIS_EMBEDDING_CACHE_ENABLED=0` for emergency bypass.

## Lifecycle Operations via Protected API

Admin lifecycle operations are exposed via retrieval API and require an admin key:

```bash
curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" \
  http://localhost:8000/v1/admin/index/generations/latest

curl -X POST -H "X-AE-API-Key: ${AE_ADMIN_KEY}" \
  http://localhost:8000/v1/admin/index/generations/validate-latest

curl -X POST -H "X-AE-API-Key: ${AE_ADMIN_KEY}" \
  http://localhost:8000/v1/admin/index/alias/promote-latest

curl -X POST -H "X-AE-API-Key: ${AE_ADMIN_KEY}" \
  http://localhost:8000/v1/admin/index/alias/rollback-latest
```

Inspect append-only lifecycle action audit:

```bash
curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" \
  "http://localhost:8000/v1/admin/index/lifecycle-audit?limit=50"
```

## Lifecycle Operations via Trusted System Paths

System-triggered lifecycle operations are supported for internal runtime/ops flows, but they must use the same `lifecycle_service` control path and write `index_lifecycle_audit` rows.

Examples:
- Minimal runtime flow (`uv run --env-file infra/.env.local python -m pipelines.minimal_slice.run_flow`) uses actor `system:run_flow`.
- Airflow DAG lifecycle tasks use actor `system:airflow:<run_id>`.
- Make lifecycle commands use actor `system:makefile`:
  - `make validate-index`
  - `make promote-index`
  - `make rollback-index`

## Airflow E2E DAG Trigger + Monitor

Primary operator DAG:
- DAG id: `audience_engine_operator_main`
- File: `pipelines/airflow_dags/audience_engine_dags.py`

Legacy internal compatibility DAG:
- DAG id: `audience_engine_minimal_slice_e2e` (internal/manual compatibility path)

Manual trigger from scheduler container:
```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec airflow-scheduler \
  airflow dags trigger audience_engine_operator_main \
  --conf '{"campaign_id":"camp_airflow_ops_001","policy_version":"policy_credit_v1","integration_profile_id":"clickhouse_postgres_export","requested_size":20}'
```

List active runs:
```bash
docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec airflow-scheduler \
  airflow dags list-runs -d audience_engine_operator_main
```

## Integration MVP Walkthrough (ClickHouse -> Policy -> Postgres Export Table)
1. Apply ClickHouse source table contract:
   ```bash
   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec -T clickhouse \
     clickhouse-client --multiquery < infra/clickhouse/sql/001_feature_mart_snapshot.sql
   ```
2. Load/refresh source rows into ClickHouse (`feature_mart_snapshot`) using your governed source feed.
3. Set integration defaults or per-run override to `clickhouse_postgres_export`.
4. Trigger run from API or Airflow DAG.
5. Inspect summary:
   ```bash
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" http://localhost:8000/v1/admin/runs/latest-summary
   ```
6. Inspect exported staging rows in Postgres:
   ```bash
   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec postgres \
     psql -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     -c "SELECT run_id, campaign_id, customer_id, final_score, rank, policy_version, exported_ts FROM audience_export_staging ORDER BY exported_ts DESC LIMIT 20;"
   ```
7. Inspect delivery outbox + delivery records (when `delivery_target_id=crm_postgres_outbox`):
   ```bash
   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec postgres \
     psql -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     -c "SELECT run_id, customer_id, delivery_target_id, outbox_status, created_at FROM audience_crm_postgres_outbox ORDER BY created_at DESC LIMIT 20;"

   docker compose --env-file infra/.env.local -f infra/docker-compose.dev.yml exec postgres \
     psql -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     -c "SELECT run_id, customer_id, delivery_target_id, delivery_status, delivered_ts FROM audience_delivery_record ORDER BY created_at DESC LIMIT 20;"
   ```
