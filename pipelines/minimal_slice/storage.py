from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

from . import config


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_import_minio():
    try:
        from minio import Minio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "MinIO integration requires dependency `minio` in runtime-minimal-slice"
        ) from exc
    return Minio


def _safe_import_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Parquet export requires dependency `pyarrow` in runtime-minimal-slice"
        ) from exc
    return pa, pq


def _safe_import_clickhouse():
    try:
        import clickhouse_connect
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "ClickHouse integration requires dependency `clickhouse-connect`"
        ) from exc
    return clickhouse_connect


def _safe_import_redis():
    try:
        import redis
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Redis cache integration requires dependency `redis`"
        ) from exc
    return redis


def _minio_client():
    Minio = _safe_import_minio()
    return Minio(
        config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        secure=config.MINIO_SECURE,
    )


def _ensure_minio_bucket(client: Any, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def _build_object_key(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p and p.strip("/"))


def write_feature_mart_parquet_to_minio(
    *,
    rows: list[dict[str, Any]],
    fs_version: str,
    run_id: str | None = None,
) -> str:
    if not rows:
        raise ValueError("Cannot write empty feature mart snapshot to MinIO")

    pa, pq = _safe_import_pyarrow()
    table = pa.Table.from_pylist(rows)
    buf = BytesIO()
    pq.write_table(table, buf, compression="snappy")
    payload = buf.getvalue()

    client = _minio_client()
    _ensure_minio_bucket(client, config.MINIO_BUCKET)

    object_key = _build_object_key(
        config.MINIO_FEATURE_MART_PREFIX,
        f"fs_version={fs_version}",
        f"run_id={run_id or _utc_stamp()}",
        "snapshot.parquet",
    )
    client.put_object(
        config.MINIO_BUCKET,
        object_key,
        BytesIO(payload),
        length=len(payload),
        content_type="application/octet-stream",
    )
    return f"s3://{config.MINIO_BUCKET}/{object_key}"


def upload_file_to_minio(
    *,
    file_path: Path,
    object_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    client = _minio_client()
    _ensure_minio_bucket(client, config.MINIO_BUCKET)
    client.fput_object(
        config.MINIO_BUCKET,
        object_key,
        str(file_path),
        content_type=content_type,
    )
    return f"s3://{config.MINIO_BUCKET}/{object_key}"


def upload_export_to_minio(*, export_path: Path, run_id: str) -> str:
    object_key = _build_object_key(
        config.MINIO_EXPORT_PREFIX,
        f"run_id={run_id}",
        export_path.name,
    )
    return upload_file_to_minio(
        file_path=export_path,
        object_key=object_key,
        content_type="application/jsonl",
    )


def read_feature_slice_from_clickhouse() -> list[dict[str, Any]]:
    clickhouse_connect = _safe_import_clickhouse()
    client = clickhouse_connect.get_client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        username=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
        database=config.CLICKHOUSE_DB,
    )

    query = config.CLICKHOUSE_FEATURE_SLICE_QUERY.strip()
    if config.CLICKHOUSE_FEATURE_SLICE_LIMIT > 0 and "limit" not in query.lower():
        query = f"{query}\nLIMIT {config.CLICKHOUSE_FEATURE_SLICE_LIMIT}"

    result = client.query(query)
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def _redis_client():
    redis = _safe_import_redis()
    return redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )


def _embedding_cache_key(emb_version: str, text: str) -> str:
    text_hash = sha256(text.encode("utf-8")).hexdigest()
    return f"{config.REDIS_EMBEDDING_CACHE_PREFIX}:{emb_version}:{text_hash}"


def get_cached_embedding(*, emb_version: str, text: str) -> list[float] | None:
    if not config.REDIS_EMBEDDING_CACHE_ENABLED:
        return None
    client = _redis_client()
    payload = client.get(_embedding_cache_key(emb_version, text))
    if not payload:
        return None
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        return None
    return [float(x) for x in parsed]


def set_cached_embedding(*, emb_version: str, text: str, vector: list[float]) -> None:
    if not config.REDIS_EMBEDDING_CACHE_ENABLED:
        return
    client = _redis_client()
    client.set(
        _embedding_cache_key(emb_version, text),
        json.dumps(vector),
        ex=config.REDIS_EMBEDDING_CACHE_TTL_SECONDS,
    )


def minio_is_configured() -> bool:
    return bool(
        config.MINIO_ENDPOINT
        and config.MINIO_ACCESS_KEY
        and config.MINIO_SECRET_KEY
        and config.MINIO_BUCKET
    )
