import hashlib
import json
import logging
import math
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    CreateAliasOperation,
    DeleteAliasOperation,
    Distance,
    PointStruct,
    VectorParams,
)

from .config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    QDRANT_ALIAS,
    QDRANT_BLUE_COLLECTION,
    QDRANT_UPSERT_BACKOFF_BASE_SECONDS,
    QDRANT_UPSERT_BACKOFF_JITTER_SECONDS,
    QDRANT_UPSERT_BACKOFF_MAX_SECONDS,
    QDRANT_UPSERT_BACKPRESSURE_SECONDS,
    QDRANT_UPSERT_BATCH_SIZE,
    QDRANT_UPSERT_PROGRESS_LOG_EVERY_BATCHES,
    QDRANT_UPSERT_RETRY_MAX_ATTEMPTS,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
RETRIEVAL_FILTER_INDEX_SCHEMA: dict[str, str] = {
    "customer_id": "keyword",
    "fs_version": "keyword",
    "emb_version": "keyword",
    "policy_version": "keyword",
    "product_line": "keyword",
    "region_code": "keyword",
    "segment_id": "keyword",
    "is_employee_flag": "bool",
    "do_not_contact_flag": "bool",
    "opt_out_flag": "bool",
    "legal_suppression_flag": "bool",
    "customer_tenure_months": "integer",
    "delinquency_12m_count": "integer",
}


def _psycopg():
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for index generation metadata persistence"
        ) from exc
    return psycopg


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _point_id(customer_id: str) -> int:
    digest = hashlib.sha256(customer_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big") & ((1 << 63) - 1)


def _postgres_conninfo() -> str:
    return (
        f"host={POSTGRES_HOST} "
        f"port={POSTGRES_PORT} "
        f"dbname={POSTGRES_DB} "
        f"user={POSTGRES_USER} "
        f"password={POSTGRES_PASSWORD}"
    )


def _ensure_index_generations_table() -> None:
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS index_generations (
                    id BIGSERIAL PRIMARY KEY,
                    alias_name TEXT NOT NULL,
                    emb_version TEXT NOT NULL,
                    dimension INTEGER NOT NULL CHECK (dimension > 0),
                    generation TEXT NOT NULL,
                    collection_name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'built',
                            'validated',
                            'promoted',
                            'rolled_back',
                            'failed'
                        )
                    ),
                    points_count INTEGER NOT NULL DEFAULT 0 CHECK (points_count >= 0),
                    previous_collection_name TEXT,
                    validation_details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    validated_at TIMESTAMPTZ,
                    promoted_at TIMESTAMPTZ,
                    rolled_back_at TIMESTAMPTZ,
                    UNIQUE (alias_name, collection_name)
                );
                """
            )
        conn.commit()


def _safe_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    token = re.sub(r"_+", "_", token).strip("_")
    return token.lower() or "unknown"


def _utc_generation() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _collection_name(emb_version: str, dimension: int, generation: str) -> str:
    return f"customers_{_safe_token(emb_version)}_{dimension}d_{generation}"


def _alias_name(emb_version: str, dimension: int) -> str:
    return f"customers_active_{_safe_token(emb_version)}_{dimension}d"


def _resolve_alias_collection(client: QdrantClient, alias_name: str) -> str | None:
    aliases = client.get_aliases().aliases
    for alias in aliases:
        if alias.alias_name == alias_name:
            return alias.collection_name
    return None


def _switch_alias(alias_name: str, collection_name: str) -> Dict[str, str]:
    client = QdrantClient(url=QDRANT_URL)
    try:
        client.update_collection_aliases(
            change_aliases_operation=[
                DeleteAliasOperation(delete_alias={"alias_name": alias_name}),
                CreateAliasOperation(
                    create_alias={
                        "collection_name": collection_name,
                        "alias_name": alias_name,
                    }
                ),
            ]
        )
    except Exception:
        client.update_collection_aliases(
            change_aliases_operation=[
                CreateAliasOperation(
                    create_alias={
                        "collection_name": collection_name,
                        "alias_name": alias_name,
                    }
                )
            ]
        )
    return {"alias": alias_name, "collection": collection_name}


def _record_generation(
    *,
    alias_name: str,
    emb_version: str,
    dimension: int,
    generation: str,
    collection_name: str,
    status: str,
    points_count: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    _ensure_index_generations_table()
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO index_generations (
                    alias_name,
                    emb_version,
                    dimension,
                    generation,
                    collection_name,
                    status,
                    points_count,
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (alias_name, collection_name)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    points_count = EXCLUDED.points_count,
                    metadata = EXCLUDED.metadata
                """,
                (
                    alias_name,
                    emb_version,
                    dimension,
                    generation,
                    collection_name,
                    status,
                    points_count,
                    json.dumps(metadata or {}),
                ),
            )
        conn.commit()


def _load_latest_generation(
    *,
    status: str | None = None,
    alias_name: str | None = None,
) -> dict[str, Any] | None:
    _ensure_index_generations_table()
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if alias_name:
        clauses.append("alias_name = %s")
        params.append(alias_name)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT alias_name, emb_version, dimension, generation, collection_name, "
        "status, points_count, previous_collection_name "
        f"FROM index_generations {where_sql} "
        "ORDER BY created_at DESC LIMIT 1"
    )
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
    if not row:
        return None
    return {
        "alias_name": row[0],
        "emb_version": row[1],
        "dimension": row[2],
        "generation": row[3],
        "collection_name": row[4],
        "status": row[5],
        "points_count": row[6],
        "previous_collection_name": row[7],
    }


def _mark_validation(
    *,
    alias_name: str,
    collection_name: str,
    details: dict[str, Any],
) -> None:
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE index_generations
                SET
                    status = 'validated',
                    validation_details = %s::jsonb,
                    validated_at = NOW()
                WHERE alias_name = %s AND collection_name = %s
                """,
                (json.dumps(details), alias_name, collection_name),
            )
        conn.commit()


def _mark_promoted(
    *,
    alias_name: str,
    collection_name: str,
    previous_collection_name: str | None,
) -> None:
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE index_generations
                SET
                    status = 'promoted',
                    previous_collection_name = %s,
                    promoted_at = NOW()
                WHERE alias_name = %s AND collection_name = %s
                """,
                (previous_collection_name, alias_name, collection_name),
            )
        conn.commit()


def _mark_rolled_back(*, alias_name: str, current_collection_name: str) -> None:
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE index_generations
                SET status = 'rolled_back', rolled_back_at = NOW()
                WHERE alias_name = %s AND collection_name = %s
                """,
                (alias_name, current_collection_name),
            )
        conn.commit()


def _create_payload_indexes(client: QdrantClient, collection_name: str) -> None:
    for key, schema in RETRIEVAL_FILTER_INDEX_SCHEMA.items():
        client.create_payload_index(
            collection_name=collection_name,
            field_name=key,
            field_schema=schema,
        )


def _vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in vector))


def _is_transient_upsert_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code in TRANSIENT_STATUS_CODES:
        return True
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int) and response_status in TRANSIENT_STATUS_CODES:
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "timeout",
            "timed out",
            "temporar",
            "service unavailable",
            "connection reset",
            "connection refused",
            "too many requests",
            "429",
            "503",
            "504",
        )
    )


def _retry_delay_seconds(attempt: int) -> float:
    delay = min(
        QDRANT_UPSERT_BACKOFF_MAX_SECONDS,
        QDRANT_UPSERT_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)),
    )
    if QDRANT_UPSERT_BACKOFF_JITTER_SECONDS > 0:
        delay += random.uniform(0.0, QDRANT_UPSERT_BACKOFF_JITTER_SECONDS)
    return delay


def _upsert_batch_with_retry(
    *,
    client: QdrantClient,
    collection_name: str,
    batch: list[PointStruct],
) -> int:
    for attempt in range(1, QDRANT_UPSERT_RETRY_MAX_ATTEMPTS + 1):
        try:
            client.upsert(collection_name=collection_name, points=batch)
            return attempt - 1
        except Exception as exc:
            transient = _is_transient_upsert_error(exc)
            if (not transient) or attempt >= QDRANT_UPSERT_RETRY_MAX_ATTEMPTS:
                raise
            delay = _retry_delay_seconds(attempt)
            logger.warning(
                "Qdrant upsert retry for %s (attempt=%d/%d, batch=%d, delay=%.2fs): %s",
                collection_name,
                attempt + 1,
                QDRANT_UPSERT_RETRY_MAX_ATTEMPTS,
                len(batch),
                delay,
                exc,
            )
            time.sleep(delay)
    return 0


def build_generation(
    *,
    embeddings_path: Path,
    vector_size: int,
    emb_version: str | None = None,
    generation: str | None = None,
    alias_name_override: str | None = None,
    collection_name_override: str | None = None,
) -> Dict[str, Any]:
    points_src = _read_jsonl(embeddings_path)
    if not points_src:
        raise ValueError(f"No embeddings found at {embeddings_path}")

    resolved_emb_version = emb_version or str(
        points_src[0].get("emb_version", "unknown")
    )
    resolved_generation = generation or _utc_generation()
    alias_name = alias_name_override or _alias_name(resolved_emb_version, vector_size)
    collection_name = collection_name_override or _collection_name(
        emb_version=resolved_emb_version,
        dimension=vector_size,
        generation=resolved_generation,
    )
    client = QdrantClient(url=QDRANT_URL)

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    _create_payload_indexes(client, collection_name)

    batch: list[PointStruct] = []
    total_points = len(points_src)
    total_retries = 0
    batches_processed = 0
    points_indexed = 0
    started_at = time.perf_counter()

    for row in points_src:
        payload = {k: v for k, v in row.items() if k != "vector"}
        batch.append(
            PointStruct(
                id=_point_id(row["customer_id"]),
                vector=row["vector"],
                payload=payload,
            )
        )
        if len(batch) >= QDRANT_UPSERT_BATCH_SIZE:
            retries = _upsert_batch_with_retry(
                client=client,
                collection_name=collection_name,
                batch=batch,
            )
            total_retries += retries
            points_indexed += len(batch)
            batches_processed += 1
            if QDRANT_UPSERT_BACKPRESSURE_SECONDS > 0:
                time.sleep(QDRANT_UPSERT_BACKPRESSURE_SECONDS)
            if (
                batches_processed % QDRANT_UPSERT_PROGRESS_LOG_EVERY_BATCHES == 0
                or points_indexed == total_points
            ):
                elapsed = max(time.perf_counter() - started_at, 1e-9)
                throughput = points_indexed / elapsed
                logger.info(
                    "Qdrant upsert progress for %s: %d/%d points, "
                    "batches=%d, retries=%d, throughput=%.2f points/s",
                    collection_name,
                    points_indexed,
                    total_points,
                    batches_processed,
                    total_retries,
                    throughput,
                )
            batch = []
    if batch:
        retries = _upsert_batch_with_retry(
            client=client,
            collection_name=collection_name,
            batch=batch,
        )
        total_retries += retries
        points_indexed += len(batch)
        batches_processed += 1

    elapsed_total = max(time.perf_counter() - started_at, 1e-9)
    throughput_total = points_indexed / elapsed_total
    logger.info(
        "Qdrant upsert completed for %s: points=%d, "
        "batches=%d, retries=%d, elapsed=%.2fs, throughput=%.2f points/s",
        collection_name,
        points_indexed,
        batches_processed,
        total_retries,
        elapsed_total,
        throughput_total,
    )

    _record_generation(
        alias_name=alias_name,
        emb_version=resolved_emb_version,
        dimension=vector_size,
        generation=resolved_generation,
        collection_name=collection_name,
        status="built",
        points_count=len(points_src),
        metadata={"embeddings_path": str(embeddings_path)},
    )
    return {
        "stage": "build_generation",
        "alias": alias_name,
        "collection": collection_name,
        "emb_version": resolved_emb_version,
        "dimension": vector_size,
        "generation": resolved_generation,
        "points_count": len(points_src),
        "upsert": {
            "batch_size": QDRANT_UPSERT_BATCH_SIZE,
            "batches": batches_processed,
            "retries": total_retries,
            "elapsed_seconds": round(elapsed_total, 4),
            "throughput_points_per_second": round(throughput_total, 2),
        },
    }


def validate_generation(
    *,
    embeddings_path: Path,
    collection_name: str,
    alias_name: str,
    expected_count: int | None = None,
    sample_size: int = 5,
) -> Dict[str, Any]:
    points_src = _read_jsonl(embeddings_path)
    if not points_src:
        raise ValueError(f"No embeddings found at {embeddings_path}")

    client = QdrantClient(url=QDRANT_URL)
    exact_count = client.count(collection_name=collection_name, exact=True).count
    expected = expected_count if expected_count is not None else len(points_src)
    count_ok = exact_count == expected
    if not count_ok:
        raise ValueError(
            f"Count check failed for {collection_name}: "
            f"expected {expected}, got {exact_count}"
        )

    sample_vector = points_src[0]["vector"]
    sample_hits = client.search(
        collection_name=collection_name,
        query_vector=sample_vector,
        limit=1,
        with_payload=True,
    )
    if not sample_hits:
        raise ValueError(f"Sample query returned no hits for {collection_name}")

    norms: list[float] = []
    for row in points_src[: max(1, sample_size)]:
        norm = _vector_norm(row["vector"])
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError(
                f"Invalid vector norm detected in {collection_name}: {norm}"
            )
        norms.append(norm)

    details = {
        "expected_count": expected,
        "actual_count": exact_count,
        "sample_hit_customer_id": (sample_hits[0].payload or {}).get("customer_id"),
        "norm_min": min(norms),
        "norm_max": max(norms),
    }
    _mark_validation(
        alias_name=alias_name,
        collection_name=collection_name,
        details=details,
    )
    return {
        "stage": "validate_generation",
        "alias": alias_name,
        "collection": collection_name,
        "checks": details,
    }


def promote_alias(*, alias_name: str, collection_name: str) -> Dict[str, Any]:
    client = QdrantClient(url=QDRANT_URL)
    previous_collection = _resolve_alias_collection(client, alias_name)
    result = _switch_alias(alias_name=alias_name, collection_name=collection_name)
    _mark_promoted(
        alias_name=alias_name,
        collection_name=collection_name,
        previous_collection_name=previous_collection,
    )
    return {
        "stage": "promote_alias",
        "alias": result["alias"],
        "collection": result["collection"],
        "previous_collection": previous_collection,
    }


def rollback_alias(*, alias_name: str) -> Dict[str, Any]:
    _ensure_index_generations_table()
    client = QdrantClient(url=QDRANT_URL)
    current_collection = _resolve_alias_collection(client, alias_name)
    if not current_collection:
        raise ValueError(f"No active alias mapping exists for {alias_name}")

    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT previous_collection_name
                FROM index_generations
                WHERE alias_name = %s AND collection_name = %s
                ORDER BY promoted_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                (alias_name, current_collection),
            )
            row = cur.fetchone()
    previous_collection = row[0] if row else None
    if not previous_collection:
        raise ValueError(
            "No rollback target recorded for "
            f"alias={alias_name}, collection={current_collection}"
        )

    result = _switch_alias(alias_name=alias_name, collection_name=previous_collection)
    _mark_rolled_back(alias_name=alias_name, current_collection_name=current_collection)
    return {
        "stage": "rollback_alias",
        "alias": result["alias"],
        "collection": result["collection"],
        "rolled_back_from": current_collection,
    }


def validate_latest_generation(*, embeddings_path: Path) -> Dict[str, Any]:
    latest = _load_latest_generation(status="built")
    if not latest:
        raise ValueError("No built generation found in metadata")
    return validate_generation(
        embeddings_path=embeddings_path,
        collection_name=latest["collection_name"],
        alias_name=latest["alias_name"],
        expected_count=latest["points_count"],
    )


def promote_latest_generation() -> Dict[str, Any]:
    latest = _load_latest_generation(status="validated")
    if not latest:
        raise ValueError("No validated generation found in metadata")
    return promote_alias(
        alias_name=latest["alias_name"],
        collection_name=latest["collection_name"],
    )


def rollback_latest_alias() -> Dict[str, Any]:
    latest = _load_latest_generation(status="promoted")
    if not latest:
        raise ValueError("No promoted generation found in metadata")
    return rollback_alias(alias_name=latest["alias_name"])


def switch_alias(
    alias_name: str = QDRANT_ALIAS,
    collection_name: str = QDRANT_BLUE_COLLECTION,
) -> Dict[str, str]:
    return _switch_alias(alias_name=alias_name, collection_name=collection_name)


def switch_alias_to_blue() -> Dict[str, str]:
    return switch_alias(alias_name=QDRANT_ALIAS, collection_name=QDRANT_BLUE_COLLECTION)


def create_or_replace_index(
    embeddings_path: Path,
    vector_size: int,
    collection_name: str = QDRANT_BLUE_COLLECTION,
    alias_name: str = QDRANT_ALIAS,
) -> Dict[str, str]:
    built = build_generation(
        embeddings_path=embeddings_path,
        vector_size=vector_size,
        alias_name_override=alias_name,
        collection_name_override=collection_name,
    )
    validate_generation(
        embeddings_path=embeddings_path,
        collection_name=built["collection"],
        alias_name=built["alias"],
        expected_count=built["points_count"],
    )
    promoted = promote_alias(
        alias_name=built["alias"],
        collection_name=built["collection"],
    )
    return {"alias": promoted["alias"], "collection": promoted["collection"]}
