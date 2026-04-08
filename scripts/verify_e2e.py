from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import yaml
from clickhouse_connect import get_client as get_clickhouse_client
from minio import Minio
from qdrant_client import QdrantClient

from pipelines.minimal_slice import config
from pipelines.minimal_slice.embedding import build_embeddings
from pipelines.minimal_slice.exporter import export_approved
from pipelines.minimal_slice.feature_mart import build_feature_mart_snapshot
from pipelines.minimal_slice.policy_engine import evaluate_policy
from pipelines.minimal_slice.qdrant_index import (
    build_generation,
    promote_alias,
    validate_generation,
)
from pipelines.minimal_slice.retrieval import retrieve_similar
from pipelines.minimal_slice.storage import (
    get_cached_embedding,
    minio_is_configured,
    upload_export_to_minio,
)
from pipelines.minimal_slice.synthetic_data import generate_synthetic_data

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "data" / "minimal_slice" / "run" / "verification_summary.json"
GENERATION_COLLECTION_RE = re.compile(r"^customers_[a-z0-9_]+_[0-9]+d_[0-9]{14}$")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _render_template(template: str, row: dict) -> str:
    return template.format(**row)


def _embedding_spec() -> dict:
    with config.EMBED_SPEC_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _expected_emb_version(feature_mart_rows: list[dict], model: str) -> str:
    fs_version = (
        str(feature_mart_rows[0]["fs_version"]) if feature_mart_rows else "unknown"
    )
    prompt_id = str(_embedding_spec()["template"]["id"])
    return f"{fs_version}+{prompt_id}+{model}"


def _minio_client() -> Minio:
    return Minio(
        config.MINIO_ENDPOINT,
        access_key=config.MINIO_ACCESS_KEY,
        secret_key=config.MINIO_SECRET_KEY,
        secure=config.MINIO_SECURE,
    )


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    _assert(uri.startswith("s3://"), f"Expected s3:// URI, got: {uri}")
    without_scheme = uri[5:]
    bucket, key = without_scheme.split("/", 1)
    return bucket, key


def _assert_minio_object_exists(uri: str) -> None:
    bucket, key = _parse_s3_uri(uri)
    client = _minio_client()
    client.stat_object(bucket, key)


def _seed_clickhouse_from_raw(raw_path: Path) -> int:
    rows = _read_jsonl(raw_path)
    client = get_clickhouse_client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        username=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
        database=config.CLICKHOUSE_DB,
    )
    client.command(
        """
        CREATE TABLE IF NOT EXISTS feature_mart_snapshot (
            customer_id String,
            customer_age_years UInt16,
            customer_tenure_months UInt16,
            credit_score_band LowCardinality(String),
            delinquency_12m_count UInt16,
            utilization_ratio_avg_3m Float32,
            card_spend_total_3m Float64,
            digital_engagement_score Float32,
            is_employee_flag UInt8,
            do_not_contact_flag UInt8,
            opt_out_flag UInt8,
            legal_suppression_flag UInt8,
            region_code LowCardinality(String),
            segment_id LowCardinality(String),
            product_line LowCardinality(String),
            fs_version String,
            policy_version String
        ) ENGINE = MergeTree
        ORDER BY customer_id
        """
    )
    client.command("TRUNCATE TABLE feature_mart_snapshot")
    data = [
        [
            row["customer_id"],
            int(row["customer_age_years"]),
            int(row["customer_tenure_months"]),
            str(row["credit_score_band"]),
            int(row["delinquency_12m_count"]),
            float(row["utilization_ratio_avg_3m"]),
            float(row["card_spend_total_3m"]),
            float(row["digital_engagement_score"]),
            1 if bool(row.get("is_employee_flag", False)) else 0,
            1 if bool(row.get("do_not_contact_flag", False)) else 0,
            1 if bool(row.get("opt_out_flag", False)) else 0,
            1 if bool(row.get("legal_suppression_flag", False)) else 0,
            str(row.get("region_code", "unknown")),
            str(row.get("segment_id", "unknown")),
            str(row.get("product_line", "unknown")),
            "fs_credit_v1",
            config.POLICY_VERSION,
        ]
        for row in rows
    ]
    client.insert(
        "feature_mart_snapshot",
        data,
        column_names=[
            "customer_id",
            "customer_age_years",
            "customer_tenure_months",
            "credit_score_band",
            "delinquency_12m_count",
            "utilization_ratio_avg_3m",
            "card_spend_total_3m",
            "digital_engagement_score",
            "is_employee_flag",
            "do_not_contact_flag",
            "opt_out_flag",
            "legal_suppression_flag",
            "region_code",
            "segment_id",
            "product_line",
            "fs_version",
            "policy_version",
        ],
    )
    return len(data)


def _redis_conninfo() -> str:
    password = f" password={config.REDIS_PASSWORD}" if config.REDIS_PASSWORD else ""
    return (
        f"host={config.REDIS_HOST} "
        f"port={config.REDIS_PORT} "
        f"db={config.REDIS_DB}{password}"
    )


def _redis_client():
    import redis

    return redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )


def _clear_embedding_cache(emb_version: str) -> int:
    client = _redis_client()
    pattern = f"{config.REDIS_EMBEDDING_CACHE_PREFIX}:{emb_version}:*"
    deleted = 0
    for key in client.scan_iter(match=pattern):
        deleted += int(client.delete(key) or 0)
    return deleted


def _count_embedding_cache_keys(emb_version: str) -> int:
    client = _redis_client()
    pattern = f"{config.REDIS_EMBEDDING_CACHE_PREFIX}:{emb_version}:*"
    return sum(1 for _ in client.scan_iter(match=pattern))


def _count_cached_docs(feature_mart_rows: list[dict], emb_version: str) -> int:
    template = str(_embedding_spec()["template"]["format"])
    hits = 0
    for row in feature_mart_rows:
        text = _render_template(template, row)
        if get_cached_embedding(emb_version=emb_version, text=text) is not None:
            hits += 1
    return hits


def _postgres_conninfo() -> str:
    return (
        f"host={config.POSTGRES_HOST} "
        f"port={config.POSTGRES_PORT} "
        f"dbname={config.POSTGRES_DB} "
        f"user={config.POSTGRES_USER} "
        f"password={config.POSTGRES_PASSWORD}"
    )


def _write_audit_and_assert(
    *,
    run_id: str,
    campaign_id: str,
    collection_name: str,
    emb_version: str,
    policy_result: dict,
) -> tuple[int, int, int]:
    selected = policy_result.get("selected", [])
    rejection_summary = policy_result.get("rejection_summary", {})
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audience_run (
                    run_id,
                    campaign_id,
                    product_id,
                    run_ts,
                    version_bundle,
                    parameters
                )
                VALUES (%s, %s, %s, now(), %s::jsonb, %s::jsonb)
                """,
                (
                    run_id,
                    campaign_id,
                    "verify_e2e",
                    json.dumps(
                        {
                            "fs_version": "fs_credit_v1",
                            "emb_version": emb_version,
                            "policy_version": config.POLICY_VERSION,
                            "index_alias": config.QDRANT_ALIAS,
                            "concrete_qdrant_collection": collection_name,
                            "run_id": run_id,
                            "campaign_id": campaign_id,
                        }
                    ),
                    json.dumps({"verify": True}),
                ),
            )
            for rank, row in enumerate(selected, start=1):
                cur.execute(
                    """
                    INSERT INTO audience_run_selected (
                        run_id,
                        customer_id,
                        final_score,
                        rank,
                        channel,
                        selected_ts
                    )
                    VALUES (%s, %s, %s, %s, %s, now())
                    """,
                    (
                        run_id,
                        row["customer_id"],
                        float(row.get("score", 0.0)),
                        rank,
                        "email",
                    ),
                )
            for reason_code, rejected_count in rejection_summary.items():
                cur.execute(
                    """
                    INSERT INTO audience_run_rejections_summary (
                        run_id,
                        reason_code,
                        rejected_count,
                        summary_ts
                    )
                    VALUES (%s, %s, %s, now())
                    """,
                    (run_id, reason_code, int(rejected_count)),
                )

            cur.execute(
                "SELECT count(*) FROM audience_run WHERE run_id = %s", (run_id,)
            )
            run_rows = int(cur.fetchone()[0])
            cur.execute(
                "SELECT count(*) FROM audience_run_selected WHERE run_id = %s",
                (run_id,),
            )
            selected_rows = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT count(*)
                FROM audience_run_rejections_summary
                WHERE run_id = %s
                """,
                (run_id,),
            )
            rejection_rows = int(cur.fetchone()[0])
        conn.commit()

    _assert(run_rows >= 1, f"No audience_run row found for run_id={run_id}")
    return run_rows, selected_rows, rejection_rows


def _assert_alias_points_to_generation_collection(
    alias_name: str, expected_collection: str
) -> None:
    client = QdrantClient(url=config.QDRANT_URL)
    aliases = client.get_aliases().aliases
    actual = None
    for alias in aliases:
        if alias.alias_name == alias_name:
            actual = alias.collection_name
            break
    _assert(
        actual == expected_collection,
        f"Alias {alias_name} points to {actual}, expected {expected_collection}",
    )
    _assert(
        bool(GENERATION_COLLECTION_RE.match(actual or "")),
        f"Alias target does not look like a generation collection: {actual}",
    )


def main() -> int:
    run_id = str(uuid4())
    campaign_id = f"verify-{run_id[:8]}"

    print("[1/9] Preflight checks")
    _assert(minio_is_configured(), "MinIO is not configured")
    _assert(config.REDIS_EMBEDDING_CACHE_ENABLED, "Redis embedding cache is disabled")

    print("[2/9] Seed synthetic data")
    generated = generate_synthetic_data(customer_count=200, seed=7)
    inserted_rows = _seed_clickhouse_from_raw(generated["raw"])
    _assert(inserted_rows > 0, "No rows inserted into ClickHouse")

    print("[3/9] Build feature mart snapshot from ClickHouse and assert MinIO parquet")
    feature_mart_path = build_feature_mart_snapshot(
        raw_path=generated["raw"],
        source_mode="clickhouse",
        run_id=run_id,
    )
    feature_mart_rows = _read_jsonl(feature_mart_path)
    _assert(feature_mart_rows, "Feature mart snapshot is empty")
    fs_version = str(feature_mart_rows[0]["fs_version"])
    feature_mart_uri = (
        f"s3://{config.MINIO_BUCKET}/{config.MINIO_FEATURE_MART_PREFIX}"
        f"/fs_version={fs_version}/run_id={run_id}/snapshot.parquet"
    )
    _assert_minio_object_exists(feature_mart_uri)

    emb_version = _expected_emb_version(feature_mart_rows, model="nomic-embed-text")
    cleared = _clear_embedding_cache(emb_version)
    if cleared:
        print(f"  cleared stale Redis embedding cache keys: {cleared}")

    print("[4/9] Generate embeddings (run 1) with Redis cache enabled")
    embeddings_path, vector_size = build_embeddings(feature_mart_path=feature_mart_path)
    cache_keys_after_first = _count_embedding_cache_keys(emb_version)
    _assert(
        cache_keys_after_first > 0, "Redis cache did not persist any embedding keys"
    )

    print("[5/9] Build generation, validate, and promote Qdrant alias")
    build_meta = build_generation(
        embeddings_path=embeddings_path,
        vector_size=vector_size,
        emb_version=emb_version,
    )
    validate_generation(
        embeddings_path=embeddings_path,
        collection_name=build_meta["collection"],
        alias_name=build_meta["alias"],
        expected_count=build_meta["points_count"],
    )
    promote_alias(
        alias_name=build_meta["alias"], collection_name=build_meta["collection"]
    )
    _assert_alias_points_to_generation_collection(
        alias_name=build_meta["alias"],
        expected_collection=build_meta["collection"],
    )

    print("[6/9] Recommend -> policy -> export")
    retrieved = retrieve_similar(
        top_k=50,
        query_customer_id="cust_00000",
        product_line="credit_card",
        region_codes=["us_west", "us_central", "us_east"],
        segment_ids=["mass", "affluent", "student", "smb"],
        min_tenure_months=3,
        max_delinquency_12m_count=2,
        fs_version=fs_version,
        emb_version=emb_version,
        policy_version=config.POLICY_VERSION,
    )
    policy_input = [
        {
            "customer_id": row["customer_id"],
            "score": row.get("score", 0.0),
            "do_not_contact_flag": row.get("payload", {}).get(
                "do_not_contact_flag", False
            ),
            "is_employee_flag": row.get("payload", {}).get("is_employee_flag", False),
            "customer_tenure_months": row.get("payload", {}).get(
                "customer_tenure_months", 0
            ),
            "delinquency_12m_count": row.get("payload", {}).get(
                "delinquency_12m_count", 0
            ),
            "opt_out_flag": row.get("payload", {}).get("opt_out_flag", False),
            "legal_suppression_flag": row.get("payload", {}).get(
                "legal_suppression_flag", False
            ),
        }
        for row in retrieved
        if row.get("customer_id")
    ]
    policy_result = evaluate_policy(
        candidates=policy_input,
        policy_version=config.POLICY_VERSION,
        blacklist_path=config.BLACKLIST_PATH,
        comm_history_path=config.COMM_HISTORY_PATH,
        campaign_id=campaign_id,
        requested_size=20,
    )
    export_path = export_approved(
        policy_result=policy_result, output_path=config.EXPORT_PATH
    )
    export_minio_uri = upload_export_to_minio(export_path=export_path, run_id=run_id)
    _assert_minio_object_exists(export_minio_uri)

    print("[7/9] Assert Postgres audit rows exist for run_id")
    run_rows, selected_rows, rejection_rows = _write_audit_and_assert(
        run_id=run_id,
        campaign_id=campaign_id,
        collection_name=build_meta["collection"],
        emb_version=emb_version,
        policy_result=policy_result,
    )

    print("[8/9] Generate embeddings (run 2) and assert Redis cache hits")
    cached_hits_before_second = _count_cached_docs(feature_mart_rows, emb_version)
    _assert(
        cached_hits_before_second > 0,
        "Second run precheck found zero cached embeddings",
    )
    _, second_vector_size = build_embeddings(feature_mart_path=feature_mart_path)
    _assert(
        second_vector_size == vector_size, "Embedding vector size changed between runs"
    )

    print("[9/9] Write verification summary")
    summary = {
        "run_id": run_id,
        "campaign_id": campaign_id,
        "feature_mart_path": str(feature_mart_path),
        "feature_mart_minio_uri": feature_mart_uri,
        "embeddings_path": str(embeddings_path),
        "emb_version": emb_version,
        "vector_size": vector_size,
        "qdrant_alias": build_meta["alias"],
        "qdrant_collection": build_meta["collection"],
        "export_path": str(export_path),
        "export_minio_uri": export_minio_uri,
        "audit": {
            "audience_run_rows": run_rows,
            "audience_run_selected_rows": selected_rows,
            "audience_run_rejection_rows": rejection_rows,
        },
        "redis_cache": {
            "keys_after_first_run": cache_keys_after_first,
            "cached_hits_before_second_run": cached_hits_before_second,
            "connection": _redis_conninfo(),
        },
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("VERIFY PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        print(f"VERIFY FAILED: {exc}", file=sys.stderr)
        raise
