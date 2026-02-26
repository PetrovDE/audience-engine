# Durable Audit Sink (Postgres)

## Purpose
The minimal slice writes immutable audience-run audit records to Postgres as an append-only sink.

## Tables

### `audience_run`
- `run_id` (UUID, PK)
- `campaign_id` (TEXT)
- `product_id` (TEXT)
- `run_ts` (TIMESTAMPTZ)
- `version_bundle` (JSONB)
- `parameters` (JSONB)
- `created_at` (TIMESTAMPTZ, default `now()`)

`version_bundle` includes the full tuple:
- `fs_version`
- `emb_version`
- `policy_version`
- `index_alias`
- `concrete_qdrant_collection`
- `run_id`
- `campaign_id`

### `audience_run_selected`
- `run_id` (UUID, FK -> `audience_run.run_id`)
- `customer_id` (TEXT)
- `final_score` (DOUBLE PRECISION)
- `rank` (INTEGER)
- `channel` (TEXT)
- `selected_ts` (TIMESTAMPTZ)
- `created_at` (TIMESTAMPTZ, default `now()`)

Primary key: (`run_id`, `customer_id`)

### `audience_run_rejections_summary`
- `run_id` (UUID, FK -> `audience_run.run_id`)
- `reason_code` (TEXT)
- `rejected_count` (INTEGER)
- `summary_ts` (TIMESTAMPTZ)
- `created_at` (TIMESTAMPTZ, default `now()`)

Primary key: (`run_id`, `reason_code`)

## Append-Only Enforcement
All audit tables block `UPDATE` and `DELETE` via trigger `forbid_audience_audit_mutation()`.

## SQL Assets
- Init script: `infra/postgres/init/001_audit_sink.sql`
- Migration script: `infra/postgres/migrations/001_audit_sink.sql`

## Minimal Slice Runtime Behavior
`pipelines/minimal_slice/run_flow.py` writes:
1. one `audience_run` row per run,
2. one `audience_run_selected` row per approved customer,
3. one `audience_run_rejections_summary` row per rejection reason code.

## Quick Verification
```sql
SELECT run_id, campaign_id, run_ts, version_bundle->>'emb_version' AS emb_version
FROM audience_run
ORDER BY run_ts DESC
LIMIT 5;
```

```sql
SELECT run_id, reason_code, rejected_count
FROM audience_run_rejections_summary
ORDER BY summary_ts DESC, reason_code;
```
