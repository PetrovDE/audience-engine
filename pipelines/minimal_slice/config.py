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
