# Index Lifecycle (Qdrant Blue/Green)

This runbook describes the generation-based index lifecycle for minimal slice.

## Naming Contract

- Collection: `customers_{emb_version}_{dimension}d_{generation}`
- Alias: `customers_active_{emb_version}_{dimension}d`

Notes:
- `emb_version` is sanitized to lowercase token-safe form for Qdrant collection/alias names.
- `generation` defaults to UTC timestamp `YYYYMMDDHHMMSS`.

## Lifecycle Stages

1. `build_generation`
- Creates a new generation collection.
- Creates payload indexes (`customer_id`, `fs_version`, `emb_version`, `policy_version`, policy features).
- Upserts embeddings in batches.
- Persists metadata row in Postgres table `index_generations` with status `built`.

2. `validate_generation`
- Validates point count against expected row count.
- Runs a sample vector query against the new generation.
- Checks vector norms for finite non-zero values.
- Updates `index_generations` status to `validated` and stores validation details.

3. `promote_alias`
- Atomically switches alias to the validated generation.
- Persists previous alias target as rollback source in `index_generations`.
- Marks generation as `promoted`.

4. `rollback_alias`
- Reads rollback target from `index_generations.previous_collection_name`.
- Atomically switches alias back to previous generation.
- Marks current generation as `rolled_back`.

## Make Targets

1. Build new generation:
```bash
make build-index
```

2. Validate latest built generation:
```bash
make validate-index
```

3. Promote latest validated generation:
```bash
make promote-index
```

4. Roll back latest promoted alias:
```bash
make rollback-index
```

## Metadata Storage

Postgres table: `index_generations`

Status values:
- `built`
- `validated`
- `promoted`
- `rolled_back`
- `failed`

Schema files:
- Init: `infra/postgres/init/002_index_generations.sql`
- Migration: `infra/postgres/migrations/002_index_generations.sql`

## Operational Guidance

- Always run `validate-index` before `promote-index`.
- Promote only one generation per alias at a time.
- If post-promotion checks fail, run `rollback-index` immediately.
- Keep old promoted collections until rollback window closes.
