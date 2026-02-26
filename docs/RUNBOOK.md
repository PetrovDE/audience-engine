# Operations Runbook

This document adds operational guidance for the Postgres audit sink.
For monitoring dashboards and metrics triage, see the root runbook: `RUNBOOK.md`.

## Audit Sink Bring-up
1. Start infra:
   ```bash
   make dev-up
   ```
2. Ensure Postgres init SQL ran (new volumes only):
   ```bash
   docker compose -f infra/docker-compose.dev.yml exec postgres \
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
- Feature mart snapshots are persisted to MinIO as Parquet:
  - `s3://<MINIO_BUCKET>/<MINIO_FEATURE_MART_PREFIX>/fs_version=<...>/run_id=<...>/snapshot.parquet`
- Approved export outputs are uploaded to MinIO using run lineage:
  - `s3://<MINIO_BUCKET>/<MINIO_EXPORT_PREFIX>/run_id=<run_id>/approved_audience.jsonl`
- Embedding cache keys are stored in Redis by `emb_version` and text hash:
  - `<REDIS_EMBEDDING_CACHE_PREFIX>:<emb_version>:<sha256>`

## Backup (Logical)
Use `pg_dump` to capture durable audit tables.

```bash
docker compose -f infra/docker-compose.dev.yml exec postgres \
  pg_dump -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
  --table=audience_run \
  --table=audience_run_selected \
  --table=audience_run_rejections_summary \
  --format=custom \
  --file=/tmp/audience_audit.dump
```

Copy backup from container:
```bash
docker compose -f infra/docker-compose.dev.yml cp postgres:/tmp/audience_audit.dump ./audience_audit.dump
```

## Restore
1. Restore into a target DB:
   ```bash
   docker compose -f infra/docker-compose.dev.yml cp ./audience_audit.dump postgres:/tmp/audience_audit.dump
   docker compose -f infra/docker-compose.dev.yml exec postgres \
     pg_restore -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     --clean --if-exists --no-owner --no-privileges /tmp/audience_audit.dump
   ```
2. Validate row counts:
   ```bash
   docker compose -f infra/docker-compose.dev.yml exec postgres \
     psql -U "${POSTGRES_USER:-audience_engine}" -d "${POSTGRES_DB:-audience_engine}" \
     -c "SELECT 'audience_run' AS table, count(*) FROM audience_run
         UNION ALL SELECT 'audience_run_selected', count(*) FROM audience_run_selected
         UNION ALL SELECT 'audience_run_rejections_summary', count(*) FROM audience_run_rejections_summary;"
   ```

## Notes
- Init SQL (`infra/postgres/init/001_audit_sink.sql`) runs only on first database initialization (empty `pgdata` volume).
- For existing environments, apply `infra/postgres/migrations/001_audit_sink.sql` manually.
- Audit tables are append-only; updates/deletes are rejected by trigger.
- If `FEATURE_SLICE_SOURCE=clickhouse`, ensure `CLICKHOUSE_FEATURE_SLICE_QUERY` returns all contract columns needed by `governance/contracts/feature_mart.yaml`.
- If MinIO credentials are unset/invalid, feature-mart Parquet and export uploads fail fast during runtime operations.
- If Redis cache is unavailable, embedding runs fail; disable cache explicitly with `REDIS_EMBEDDING_CACHE_ENABLED=0` for emergency bypass.
