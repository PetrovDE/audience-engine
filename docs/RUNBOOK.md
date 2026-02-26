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
