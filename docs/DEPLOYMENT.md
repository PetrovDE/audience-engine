# Deployment (M3 Infra Skeleton)

This document describes host prerequisites and bootstrap verification for the Audience Engine infra skeleton.

## 1) NVIDIA Drivers (GPU host)

1. Install a recent NVIDIA driver on each GPU node.
2. Reboot and verify GPU visibility:

```bash
nvidia-smi
```

Expected: at least one GPU listed, no driver/runtime errors.

## 2) NVIDIA Container Toolkit

Install NVIDIA container runtime support so Docker can pass GPUs into containers.

Ubuntu/Debian example:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify Docker GPU passthrough:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi
```

## 3) Disk Layout (recommended)

Keep data paths separated by workload class to reduce noisy-neighbor I/O.

- `/srv/audience-engine/postgres` -> Postgres volume (`pgdata`)
- `/srv/audience-engine/clickhouse` -> ClickHouse volume (`clickhousedata`)
- `/srv/audience-engine/qdrant` -> Qdrant storage (`qdrantdata`)
- `/srv/audience-engine/minio` -> object storage (`miniodata`)
- `/srv/audience-engine/redis` -> Redis appendonly (`redisdata`)
- `/srv/audience-engine/ollama` -> model cache (`ollamadata`)
- `/srv/audience-engine/airflow` -> DAG/log/plugin volumes

Suggested capacity planning baseline:

- Fast SSD/NVMe for Postgres, ClickHouse, Qdrant
- Large-capacity disk for MinIO and Ollama model cache
- Keep at least 30% free space to avoid severe compaction/index degradation

If you move from named volumes to host bind mounts, update `infra/docker-compose.yml` and `infra/docker-compose.dev.yml` accordingly.

## 4) Bring-up

1. Copy environment template:

```bash
cp infra/.env.example infra/.env
```

2. Set strong secrets in `infra/.env`:
- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `AIRFLOW_FERNET_KEY`
- `AIRFLOW_WEBSERVER_SECRET_KEY`
- `AIRFLOW_ADMIN_PASSWORD`

4. Set runtime data-path controls for minimal slice storage integration:
- `FEATURE_SLICE_SOURCE=snapshot` or `FEATURE_SLICE_SOURCE=clickhouse`
- `MINIO_ENDPOINT` (default `localhost:9001` in dev compose)
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`
- `MINIO_BUCKET` (default `audience-engine`)
- `MINIO_FEATURE_MART_PREFIX` (default `minimal_slice/feature_mart`)
- `MINIO_EXPORT_PREFIX` (default `minimal_slice/exports`)
- `CLICKHOUSE_FEATURE_SLICE_QUERY` (must return governed feature-mart columns)
- `CLICKHOUSE_FEATURE_SLICE_LIMIT`
- `REDIS_EMBEDDING_CACHE_ENABLED=1`
- `REDIS_EMBEDDING_CACHE_PREFIX` (default `ae:emb_cache`)
- `REDIS_EMBEDDING_CACHE_TTL_SECONDS`

3. Start stack:

```bash
make dev-up
```

## 5) Verification Steps

### Service status

```bash
make ps
```

All services should be `Up` / `healthy`.

### Endpoint checks (from host)

```bash
curl -fsS http://localhost:6333/healthz
curl -fsS http://localhost:8123/ping
curl -fsS http://localhost:9001/minio/health/live
curl -fsS http://localhost:11434/api/tags
docker compose --env-file infra/.env -f infra/docker-compose.dev.yml exec -T redis redis-cli ping
```

### GPU check (inside Ollama container)

```bash
docker compose --env-file infra/.env -f infra/docker-compose.dev.yml exec -T ollama nvidia-smi
```

Expected: NVIDIA device list visible from inside the container.

### Embedding runtime GPU preflight checklist

Embedding jobs/services now fail fast before embedding calls when no GPU is detected.

Run this checklist before `build_embeddings`, minimal-slice flow runs, or retrieval calls that use `query_text`:

1. Host GPU is visible:

```bash
nvidia-smi
```

2. Docker GPU passthrough works:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi
```

3. Ollama service container sees GPU:

```bash
docker compose --env-file infra/.env -f infra/docker-compose.dev.yml exec -T ollama nvidia-smi
```

4. Optional Python-level check (if `torch` is installed in the runtime):

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

If preflight fails at runtime, use the remediation message from the exception and verify NVIDIA driver + NVIDIA Container Toolkit installation steps in sections 1 and 2 of this document.

### Airflow check

Open `http://localhost:8080` and log in with `AIRFLOW_ADMIN_USERNAME` / `AIRFLOW_ADMIN_PASSWORD` from `infra/.env`.

### Data-path integration checks

1. ClickHouse query contract check:

```bash
docker compose --env-file infra/.env -f infra/docker-compose.dev.yml exec -T clickhouse \
  clickhouse-client --query "${CLICKHOUSE_FEATURE_SLICE_QUERY:-SELECT 1}"
```

2. MinIO bucket/object check (after one minimal-slice run):

```bash
docker compose --env-file infra/.env -f infra/docker-compose.dev.yml exec -T minio \
  mc ls local/${MINIO_BUCKET:-audience-engine}/minimal_slice
```

Expected object layout:
- `minimal_slice/feature_mart/fs_version=<...>/run_id=<...>/snapshot.parquet`
- `minimal_slice/exports/run_id=<...>/approved_audience.jsonl`

3. Redis embedding cache check (after one embedding run):

```bash
docker compose --env-file infra/.env -f infra/docker-compose.dev.yml exec -T redis \
  redis-cli --scan --pattern "${REDIS_EMBEDDING_CACHE_PREFIX:-ae:emb_cache}:*"
```

## 6) Production-shaped notes

- `infra/docker-compose.yml` intentionally avoids host port publishing by default.
- Put ingress/reverse-proxy, TLS termination, and auth in front of Airflow/MinIO APIs.
- Run backups for Postgres, ClickHouse, Qdrant, and MinIO before promoting environments.
- For real production, split Airflow into dedicated webserver/scheduler/worker services and externalize secrets.
