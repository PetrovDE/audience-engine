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

## Minimal Slice Runtime Behavior
`pipelines/minimal_slice/run_flow.py` writes:
1. one `audience_run` row per run,
2. one `audience_run_selected` row per approved customer,
3. one `audience_run_rejections_summary` row per rejection reason code.
4. one `policy_decision_audit` row per evaluated customer decision.

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
