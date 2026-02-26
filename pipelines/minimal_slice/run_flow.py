import json
from datetime import datetime, timezone

from .config import (
    BLACKLIST_PATH,
    COMM_HISTORY_PATH,
    EXPORT_PATH,
    FEATURE_MART_PATH,
    RAW_PATH,
    SUMMARY_PATH,
)
from .embedding import build_embeddings
from .exporter import export_approved
from .feature_mart import build_feature_mart_snapshot
from .policy_engine import evaluate_policy
from .qdrant_index import create_or_replace_index
from .retrieval import retrieve_similar
from .synthetic_data import generate_synthetic_data


def run_minimal_vertical_slice() -> dict:
    generated = generate_synthetic_data(customer_count=200, seed=7)
    feature_mart_path = build_feature_mart_snapshot(
        raw_path=generated["raw"], output_path=FEATURE_MART_PATH
    )
    embeddings_path, vector_size = build_embeddings(feature_mart_path=feature_mart_path)
    index_meta = create_or_replace_index(
        embeddings_path=embeddings_path, vector_size=vector_size
    )

    query_customer = "cust_00000"
    retrieved = retrieve_similar(top_k=50, query_customer_id=query_customer)
    policy_input = [{"customer_id": row["customer_id"]} for row in retrieved]
    policy_result = evaluate_policy(
        candidates=policy_input,
        blacklist_path=BLACKLIST_PATH,
        comm_history_path=COMM_HISTORY_PATH,
        daily_freq_cap=2,
    )
    export_path = export_approved(policy_result=policy_result, output_path=EXPORT_PATH)

    summary = {
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "versions": {
            "fs_version": "fs_credit_v1",
            "policy_version": "policy_credit_v1",
        },
        "inputs": {
            "raw_path": str(RAW_PATH),
            "feature_mart_path": str(feature_mart_path),
            "embeddings_path": str(embeddings_path),
            "blacklist_path": str(BLACKLIST_PATH),
            "comm_history_path": str(COMM_HISTORY_PATH),
        },
        "index": index_meta,
        "retrieval": {"query_customer_id": query_customer, "retrieved_count": len(retrieved)},
        "policy": policy_result["summary"],
        "export_path": str(export_path),
    }

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


if __name__ == "__main__":
    result = run_minimal_vertical_slice()
    print(json.dumps(result, indent=2))
