import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "minimal_slice"
RUN_DIR = DATA_DIR / "run"
RAW_PATH = RUN_DIR / "synthetic_customers.jsonl"
BLACKLIST_PATH = RUN_DIR / "blacklist.txt"
COMM_HISTORY_PATH = RUN_DIR / "comm_history.jsonl"
FEATURE_MART_PATH = RUN_DIR / "feature_mart_snapshot.jsonl"
EMBEDDINGS_PATH = RUN_DIR / "embeddings.jsonl"
EXPORT_PATH = RUN_DIR / "approved_audience.jsonl"
SUMMARY_PATH = RUN_DIR / "run_summary.json"

GOVERNANCE_DIR = ROOT / "governance"
FEATURE_SET_PATH = GOVERNANCE_DIR / "features" / "feature_sets" / "fs_credit_v1.yaml"
EMBED_SPEC_PATH = (
    GOVERNANCE_DIR / "embeddings" / "embedding_specs" / "emb_llm_v1.yaml"
)
REASON_CODES_PATH = GOVERNANCE_DIR / "dictionaries" / "reason_codes.yaml"

QDRANT_URL = "http://localhost:6333"
QDRANT_ALIAS = "audience-serving"
QDRANT_BLUE_COLLECTION = "audience-credit-v1-blue"
QDRANT_UPSERT_BATCH_SIZE = max(1, int(os.getenv("QDRANT_UPSERT_BATCH_SIZE", "256")))
QDRANT_UPSERT_RETRY_MAX_ATTEMPTS = max(
    1, int(os.getenv("QDRANT_UPSERT_RETRY_MAX_ATTEMPTS", "5"))
)
QDRANT_UPSERT_BACKOFF_BASE_SECONDS = max(
    0.0, float(os.getenv("QDRANT_UPSERT_BACKOFF_BASE_SECONDS", "0.5"))
)
QDRANT_UPSERT_BACKOFF_MAX_SECONDS = max(
    QDRANT_UPSERT_BACKOFF_BASE_SECONDS,
    float(os.getenv("QDRANT_UPSERT_BACKOFF_MAX_SECONDS", "8.0")),
)
QDRANT_UPSERT_BACKOFF_JITTER_SECONDS = max(
    0.0, float(os.getenv("QDRANT_UPSERT_BACKOFF_JITTER_SECONDS", "0.1"))
)
QDRANT_UPSERT_BACKPRESSURE_SECONDS = max(
    0.0, float(os.getenv("QDRANT_UPSERT_BACKPRESSURE_SECONDS", "0.0"))
)
QDRANT_UPSERT_PROGRESS_LOG_EVERY_BATCHES = max(
    1, int(os.getenv("QDRANT_UPSERT_PROGRESS_LOG_EVERY_BATCHES", "10"))
)
POLICY_VERSION = "policy_credit_v1"

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "audience_engine")
POSTGRES_USER = os.getenv("POSTGRES_USER", "audience_engine")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "change_me")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9001")
MINIO_ACCESS_KEY = os.getenv(
    "MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", "minioadmin")
)
MINIO_SECRET_KEY = os.getenv(
    "MINIO_SECRET_KEY",
    os.getenv("MINIO_ROOT_PASSWORD", "change_me_please"),
)
MINIO_SECURE = os.getenv("MINIO_SECURE", "0").lower() in {"1", "true", "yes"}
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "audience-engine")
MINIO_FEATURE_MART_PREFIX = os.getenv(
    "MINIO_FEATURE_MART_PREFIX", "minimal_slice/feature_mart"
)
MINIO_EXPORT_PREFIX = os.getenv("MINIO_EXPORT_PREFIX", "minimal_slice/exports")

FEATURE_SLICE_SOURCE = os.getenv("FEATURE_SLICE_SOURCE", "snapshot")

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "audience_engine")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "audience_engine")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "change_me")
CLICKHOUSE_FEATURE_SLICE_QUERY = os.getenv(
    "CLICKHOUSE_FEATURE_SLICE_QUERY",
    (
        "SELECT customer_id, customer_age_years, customer_tenure_months, "
        "credit_score_band, delinquency_12m_count, utilization_ratio_avg_3m, "
        "card_spend_total_3m, digital_engagement_score, is_employee_flag, "
        "do_not_contact_flag, opt_out_flag, legal_suppression_flag, "
        "region_code, segment_id, product_line "
        "FROM feature_mart_snapshot"
    ),
)
CLICKHOUSE_FEATURE_SLICE_LIMIT = int(os.getenv("CLICKHOUSE_FEATURE_SLICE_LIMIT", "5000"))

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_EMBEDDING_CACHE_ENABLED = os.getenv("REDIS_EMBEDDING_CACHE_ENABLED", "1").lower() in {
    "1",
    "true",
    "yes",
}
REDIS_EMBEDDING_CACHE_PREFIX = os.getenv(
    "REDIS_EMBEDDING_CACHE_PREFIX", "ae:emb_cache"
)
REDIS_EMBEDDING_CACHE_TTL_SECONDS = int(
    os.getenv("REDIS_EMBEDDING_CACHE_TTL_SECONDS", "86400")
)
