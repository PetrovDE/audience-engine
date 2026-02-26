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
POLICY_VERSION = "policy_credit_v1"
