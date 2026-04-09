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

### `policy_decision_audit`
- `id` (BIGSERIAL, PK)
- `run_id` (UUID, FK -> `audience_run.run_id`)
- `campaign_id` (TEXT)
- `customer_id` (TEXT)
- `decision` (TEXT, `approve|reject`)
- `reason_codes` (TEXT[])
- `policy_version` (TEXT)
- `fs_version` (TEXT)
- `emb_version` (TEXT)
- `model_version` (TEXT)
- `index_alias` (TEXT)
- `index_generation` (TEXT, resolved collection when available)
- `decision_ts` (TIMESTAMPTZ)
- `decision_explanation` (JSONB)
- `created_at` (TIMESTAMPTZ, default `now()`)

Uniqueness: (`run_id`, `customer_id`)

### `audience_export_staging`
- `id` (BIGSERIAL, PK)
- `run_id` (UUID, FK -> `audience_run.run_id`)
- `campaign_id` (TEXT)
- `customer_id` (TEXT)
- `status` (TEXT, currently `approve`)
- `final_score` (DOUBLE PRECISION)
- `rank` (INTEGER)
- `channel` (TEXT)
- `policy_version` (TEXT)
- `fs_version` (TEXT)
- `emb_version` (TEXT)
- `model_version` (TEXT)
- `index_alias` (TEXT)
- `index_generation` (TEXT)
- `integration_profile_id` (TEXT)
- `source_id` (TEXT)
- `export_target_id` (TEXT)
- `exported_ts` (TIMESTAMPTZ)
- `export_context` (JSONB)
- `created_at` (TIMESTAMPTZ, default `now()`)

Uniqueness: (`run_id`, `customer_id`)

### `index_lifecycle_audit`
- `id` (BIGSERIAL, PK)
- `action` (TEXT, `validate_generation|promote_alias|rollback_alias`)
- `alias_name` (TEXT)
- `target_collection_name` (TEXT, nullable)
- `previous_collection_name` (TEXT, nullable)
- `actor_role` (TEXT)
- `actor_id` (TEXT)
- `outcome` (TEXT, `success|failed`)
- `details` (JSONB)
- `action_ts` (TIMESTAMPTZ)
- `created_at` (TIMESTAMPTZ, default `now()`)

## Append-Only Enforcement
All audit tables block `UPDATE` and `DELETE` via trigger `forbid_audience_audit_mutation()`.

## SQL Assets
- Init script: `infra/postgres/init/001_audit_sink.sql`
- Migration script: `infra/postgres/migrations/001_audit_sink.sql`
- Init script: `infra/postgres/init/003_policy_decision_audit.sql`
- Migration script: `infra/postgres/migrations/003_policy_decision_audit.sql`
- Init script: `infra/postgres/init/004_index_lifecycle_audit.sql`
- Migration script: `infra/postgres/migrations/004_index_lifecycle_audit.sql`
- Init script: `infra/postgres/init/005_export_staging.sql`
- Migration script: `infra/postgres/migrations/005_export_staging.sql`

## Minimal Slice Runtime Behavior
`pipelines/minimal_slice/run_flow.py` writes:
1. one `audience_run` row per run,
2. one `audience_run_selected` row per approved customer,
3. one `audience_run_rejections_summary` row per rejection reason code.
4. one `policy_decision_audit` row per evaluated customer decision.
5. when the `postgres_export_table` target is selected, one `audience_export_staging` row per approved customer.

Operational control-plane run history is also appended to:
- `data/minimal_slice/control_plane/run_events.jsonl`
- This file is for operator recent-run visibility (including failed runs) and does not replace durable Postgres audit tables.

Lifecycle actions (`validate_generation`, `promote_alias`, `rollback_alias`) write `index_lifecycle_audit` rows through `pipelines/minimal_slice/lifecycle_service.py` for both admin and system-triggered flows.

Actor identity conventions:
- Admin API path: hashed API-key principal identity (for example `admin:<fingerprint>`).
- Minimal runtime path: `system:run_flow`.
- Airflow path: `system:airflow:<run_id>`.
- Make/CLI path: `system:makefile`.

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

```sql
SELECT run_id, customer_id, decision, reason_codes, policy_version, emb_version, model_version
FROM policy_decision_audit
ORDER BY decision_ts DESC
LIMIT 20;
```

```sql
SELECT action, alias_name, target_collection_name, actor_role, actor_id, outcome, action_ts
FROM index_lifecycle_audit
ORDER BY action_ts DESC
LIMIT 20;
```

```sql
SELECT run_id, campaign_id, customer_id, final_score, rank, policy_version, exported_ts
FROM audience_export_staging
ORDER BY exported_ts DESC
LIMIT 20;
```
