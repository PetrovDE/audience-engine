# Operations Runbook

This document adds operational guidance for the Postgres audit sink.
For monitoring dashboards and metrics triage, see the root runbook: `../RUNBOOK.md`.
Index generation lifecycle SOP moved to `docs/INDEX_LIFECYCLE.md`.
Host/bootstrap deployment steps moved to `docs/DEPLOYMENT.md`.

## Operator Workflow (Primary)
Use this sequence for operational usage.

1. Inspect control model and current defaults:
   ```bash
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" http://localhost:8000/v1/admin/control-plane/model
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" http://localhost:8000/v1/admin/control-plane/defaults
   ```
2. Inspect implemented integrations and policies:
   ```bash
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" "http://localhost:8000/v1/admin/control-plane/integrations?include_planned=false"
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" http://localhost:8000/v1/admin/control-plane/policies
   ```
   Readiness interpretation:
   - `runtime_runnable=true` is the operator-safe gate.
   - For `runtime_readiness_mode=config_and_connectivity`, both config and a live lightweight connectivity probe succeeded.
   - For `runtime_readiness_mode=config_only`, config validation passed and no network probe is required for that connector type.
3. (Optional) Update operator defaults:
   ```bash
   curl -X PUT -H "X-AE-API-Key: ${AE_ADMIN_KEY}" -H "Content-Type: application/json" \
     -d '{"default_policy_version":"policy_credit_v1","default_integration_profile_id":"clickhouse_postgres_export"}' \
     http://localhost:8000/v1/admin/control-plane/defaults
   ```
4. Trigger main run (policy/profile can be overridden per run):
   ```bash
   curl -X POST -H "X-AE-API-Key: ${AE_ADMIN_KEY}" -H "Content-Type: application/json" \
     -d '{"campaign_id":"camp_ops_001","policy_version":"policy_credit_v1","integration_profile_id":"clickhouse_postgres_export","requested_size":20}' \
     http://localhost:8000/v1/admin/runs/trigger
   ```
   API-triggered runs and Airflow-triggered runs are separate orchestrators over the same governed runtime modules.
5. Monitor run and export status:
   ```bash
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" http://localhost:8000/v1/admin/runs/latest-summary
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" "http://localhost:8000/v1/admin/runs/recent?limit=20"
   ```
   For `postgres_export_table`, summary export metadata includes:
   - `rows_attempted`: approved rows attempted for staging insert.
   - `rows_written`: actually inserted rows.
   - `rows_skipped_conflict`: duplicate `(run_id, customer_id)` rows skipped by idempotent conflict handling.
6. Inspect lifecycle and policy audit if needed:
   ```bash
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" "http://localhost:8000/v1/admin/index/lifecycle-audit?limit=20"
   curl -H "X-AE-API-Key: ${AE_ADMIN_KEY}" http://localhost:8000/v1/policy/decisions/<run_id>/<customer_id>
   ```

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
- Audit tables are append-only; updates/deletes are rejected by trigger.
- Policy decision explain endpoint is available at `GET /v1/policy/decisions/{run_id}/{customer_id}` via retrieval API.
- If `FEATURE_SLICE_SOURCE=clickhouse`, ensure `CLICKHOUSE_FEATURE_SLICE_QUERY` returns all contract columns needed by `governance/contracts/feature_mart.yaml`.
- For `clickhouse_postgres_export`, validate export-target settings:
  - `EXPORT_POSTGRES_HOST`, `EXPORT_POSTGRES_PORT`, `EXPORT_POSTGRES_DB`
  - `EXPORT_POSTGRES_USER`, `EXPORT_POSTGRES_PASSWORD`
  - `EXPORT_POSTGRES_SCHEMA`, `EXPORT_POSTGRES_TABLE`
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
