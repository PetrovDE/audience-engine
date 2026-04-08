# End-to-End Verification (post-E1)

## Prerequisites
- Docker Engine with Compose v2.
- Python/`uv` dependencies installed (`make bootstrap`).
- `infra/.env.local` exists and has valid credentials for:
  - Postgres
  - MinIO
  - Redis
  - ClickHouse
  - Qdrant
- External Ollama endpoint is reachable (`OLLAMA_BASE_URL`, default `http://localhost:11434` for host-run verification).
- NVIDIA driver + GPU runtime working on the host where Ollama executes embeddings.

## Exact Commands
```bash
make verify
```

Optional cleanup after verification:
```bash
make dev-down
```

## What `make verify` does
1. `docker compose` dev stack up (`infra/docker-compose.dev.yml`).
2. Seeds synthetic customers.
3. Loads synthetic rows into ClickHouse table `feature_mart_snapshot`.
4. Builds feature mart snapshot from ClickHouse and asserts MinIO parquet exists.
5. Builds embeddings with Redis cache enabled (run 1).
6. Builds Qdrant generation, validates it, and promotes alias.
7. Runs retrieval -> policy -> export.
8. Uploads export to MinIO and asserts object exists.
9. Writes Postgres audit rows and asserts they exist for `run_id`.
10. Runs embeddings again (run 2) and asserts Redis cache hits exist.
11. Writes summary to `data/minimal_slice/run/verification_summary.json`.

## Expected Output
- Terminal ends with: `VERIFY PASSED`.
- Printed JSON summary includes:
  - `run_id`
  - `feature_mart_minio_uri`
  - `export_minio_uri`
  - `qdrant_alias` + `qdrant_collection`
  - `audit.audience_run_rows` >= 1
  - `redis_cache.cached_hits_before_second_run` > 0
- File exists: `data/minimal_slice/run/verification_summary.json`.

## Troubleshooting
- GPU preflight failure:
  - Verify `nvidia-smi` on host.
  - Verify Docker GPU passthrough (`docker run --rm --gpus all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi`).
- MinIO object assertion fails:
  - Check `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET` in `infra/.env.local`.
  - Ensure MinIO service is healthy: `make ps`.
- ClickHouse step fails:
  - Confirm ClickHouse credentials/port in `infra/.env.local`.
  - Ensure `clickhouse` service is healthy: `make ps`.
- Redis cache assertion fails:
  - Ensure `REDIS_EMBEDDING_CACHE_ENABLED=1`.
  - Ensure `redis` service is healthy and reachable.
- Postgres audit assertion fails:
  - Ensure `postgres` service is healthy and credentials in `infra/.env.local` are correct.
