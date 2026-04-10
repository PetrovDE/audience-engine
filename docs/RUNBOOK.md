# Operations Runbook

This document adds operational guidance for the Postgres audit sink.
For monitoring dashboards and metrics triage, see the root runbook: `../RUNBOOK.md`.
Index generation lifecycle SOP moved to `docs/INDEX_LIFECYCLE.md`.
Host/bootstrap deployment steps moved to `docs/DEPLOYMENT.md`.

## Operator Workflow (Primary)
Use this sequence for operational usage.

1. Open the operator UI in browser:
   ```text
   http://localhost:8000/operator
   ```
2. Login with an admin API key from `AE_ADMIN_API_KEYS`.
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
   python -m pipelines.minimal_slice.run_flow
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
- Minimal runtime flow (`python -m pipelines.minimal_slice.run_flow`) uses actor `system:run_flow`.
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
