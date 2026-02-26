import json
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import yaml

from pipelines.version_bundle import (
    VersionBundle,
    build_version_bundle,
    preflight_version_bundle,
)

from .config import (
    BLACKLIST_PATH,
    COMM_HISTORY_PATH,
    EMBED_SPEC_PATH,
    EXPORT_PATH,
    FEATURE_MART_PATH,
    FEATURE_SET_PATH,
    GOVERNANCE_DIR,
    POLICY_VERSION,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    QDRANT_ALIAS,
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


def _load_feature_set_version() -> str:
    with FEATURE_SET_PATH.open("r", encoding="utf-8") as f:
        fs = yaml.safe_load(f)
    return fs["fs_version"]


def _build_and_validate_bundle(campaign_id: str) -> VersionBundle:
    bundle = build_version_bundle(
        fs_version=_load_feature_set_version(),
        policy_version=POLICY_VERSION,
        index_alias=QDRANT_ALIAS,
        campaign_id=campaign_id,
        embedding_spec_path=EMBED_SPEC_PATH,
        model_version="nomic-embed-text",
    )
    preflight_version_bundle(
        bundle=bundle,
        embedding_spec_path=EMBED_SPEC_PATH,
        policy_registry_path=GOVERNANCE_DIR / "policies" / "policy_registry.yaml",
        feature_registry_path=GOVERNANCE_DIR / "features" / "feature_registry.yaml",
        logged_fields={
            "customer_id",
            "fs_version",
            "emb_version",
            "policy_version",
            "is_employee_flag",
            "do_not_contact_flag",
            "customer_tenure_months",
            "delinquency_12m_count",
            "opt_out_flag",
            "legal_suppression_flag",
            "product_line",
            "region_code",
            "segment_id",
        },
    )
    return bundle


def _postgres_conninfo() -> str:
    return (
        f"host={POSTGRES_HOST} "
        f"port={POSTGRES_PORT} "
        f"dbname={POSTGRES_DB} "
        f"user={POSTGRES_USER} "
        f"password={POSTGRES_PASSWORD}"
    )


def _build_audit_rows(
    *,
    retrieved: list[dict],
    policy_result: dict,
    bundle: VersionBundle,
    run_ts: str,
    product_id: str,
    channel: str,
    resolved_collection: str,
) -> tuple[dict, list[tuple], list[tuple]]:
    ranking: dict[str, tuple[float, int]] = {}
    for idx, row in enumerate(retrieved, start=1):
        customer_id = row.get("customer_id")
        if not customer_id:
            continue
        ranking[customer_id] = (float(row.get("score", 0.0)), idx)

    selected_rows: list[tuple] = []
    selected_customer_ids = {
        row["customer_id"] for row in policy_result.get("selected", [])
    }
    reject_counts: Counter = Counter(policy_result.get("rejection_summary", {}))
    for row in policy_result["results"]:
        customer_id = row["customer_id"]
        if customer_id in selected_customer_ids:
            score, rank = ranking.get(customer_id, (0.0, 0))
            selected_rows.append(
                (bundle.run_id, customer_id, score, rank, channel, run_ts)
            )
            continue

    rejection_rows = [
        (bundle.run_id, reason_code, count, run_ts)
        for reason_code, count in sorted(reject_counts.items())
    ]
    run_row = {
        "run_id": bundle.run_id,
        "campaign_id": bundle.campaign_id,
        "product_id": product_id,
        "run_ts": run_ts,
        "version_bundle": {
            "fs_version": bundle.fs_version,
            "emb_version": bundle.emb_version,
            "policy_version": bundle.policy_version,
            "index_alias": bundle.index_alias,
            "concrete_qdrant_collection": resolved_collection,
            "run_id": bundle.run_id,
            "campaign_id": bundle.campaign_id,
        },
        "parameters": {
            "query_customer_id": "cust_00000",
            "retrieval_top_k": len(retrieved),
            "channel": channel,
            "requested_size": len(selected_rows),
            "policy_rejection_summary": dict(reject_counts),
        },
    }
    return run_row, selected_rows, rejection_rows


def _write_audit_to_postgres(
    *,
    run_row: dict,
    selected_rows: list[tuple],
    rejection_rows: list[tuple],
) -> None:
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
                VALUES (%s, %s, %s, %s::timestamptz, %s::jsonb, %s::jsonb)
                """,
                (
                    run_row["run_id"],
                    run_row["campaign_id"],
                    run_row["product_id"],
                    run_row["run_ts"],
                    json.dumps(run_row["version_bundle"]),
                    json.dumps(run_row["parameters"]),
                ),
            )
            if selected_rows:
                cur.executemany(
                    """
                    INSERT INTO audience_run_selected (
                        run_id,
                        customer_id,
                        final_score,
                        rank,
                        channel,
                        selected_ts
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::timestamptz)
                    """,
                    selected_rows,
                )
            if rejection_rows:
                cur.executemany(
                    """
                    INSERT INTO audience_run_rejections_summary (
                        run_id,
                        reason_code,
                        rejected_count,
                        summary_ts
                    )
                    VALUES (%s, %s, %s, %s::timestamptz)
                    """,
                    rejection_rows,
                )
        conn.commit()


def run_minimal_vertical_slice(campaign_id: str | None = None) -> dict:
    bundle = _build_and_validate_bundle(campaign_id=campaign_id or str(uuid4()))
    generated = generate_synthetic_data(customer_count=200, seed=7)
    feature_mart_path = build_feature_mart_snapshot(
        raw_path=generated["raw"], output_path=FEATURE_MART_PATH
    )
    embeddings_path, vector_size = build_embeddings(feature_mart_path=feature_mart_path)
    index_meta = create_or_replace_index(
        embeddings_path=embeddings_path,
        vector_size=vector_size,
        collection_name=bundle.concrete_qdrant_collection,
        alias_name=bundle.index_alias,
    )

    query_customer = "cust_00000"
    retrieved = retrieve_similar(
        top_k=50,
        query_customer_id=query_customer,
        product_line="credit_card",
        region_codes=["us_west", "us_central", "us_east"],
        segment_ids=["mass", "affluent", "student", "smb"],
        min_tenure_months=3,
        max_delinquency_12m_count=2,
    )
    policy_input = []
    for row in retrieved:
        payload = row.get("payload") or {}
        policy_input.append(
            {
                "customer_id": row["customer_id"],
                "score": row.get("score", 0.0),
                "do_not_contact_flag": payload.get("do_not_contact_flag", False),
                "is_employee_flag": payload.get("is_employee_flag", False),
                "customer_tenure_months": payload.get("customer_tenure_months", 0),
                "delinquency_12m_count": payload.get("delinquency_12m_count", 0),
                "opt_out_flag": payload.get("opt_out_flag", False),
                "legal_suppression_flag": payload.get("legal_suppression_flag", False),
            }
        )
    policy_result = evaluate_policy(
        candidates=policy_input,
        policy_version=bundle.policy_version,
        blacklist_path=BLACKLIST_PATH,
        comm_history_path=COMM_HISTORY_PATH,
        campaign_id=bundle.campaign_id,
        requested_size=20,
    )
    export_ready = {
        **policy_result,
        "results": [
            row for row in policy_result["results"] if row.get("selected", False)
        ],
    }
    export_path = export_approved(policy_result=export_ready, output_path=EXPORT_PATH)
    run_ts = datetime.now(timezone.utc).isoformat()
    run_row, selected_rows, rejection_rows = _build_audit_rows(
        retrieved=retrieved,
        policy_result=policy_result,
        bundle=bundle,
        run_ts=run_ts,
        product_id="minimal_slice",
        channel="email",
        resolved_collection=index_meta["collection"],
    )
    _write_audit_to_postgres(
        run_row=run_row,
        selected_rows=selected_rows,
        rejection_rows=rejection_rows,
    )

    summary = {
        "run_ts": run_ts,
        "versions": run_row["version_bundle"],
        "inputs": {
            "raw_path": str(RAW_PATH),
            "feature_mart_path": str(feature_mart_path),
            "embeddings_path": str(embeddings_path),
            "blacklist_path": str(BLACKLIST_PATH),
            "comm_history_path": str(COMM_HISTORY_PATH),
        },
        "index": index_meta,
        "retrieval": {
            "query_customer_id": query_customer,
            "retrieved_count": len(retrieved),
        },
        "policy": policy_result["summary"],
        "export_path": str(export_path),
        "audit": {
            "postgres": {
                "run_table": "audience_run",
                "selected_rows_written": len(selected_rows),
                "rejection_summary_rows_written": len(rejection_rows),
            }
        },
    }

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


if __name__ == "__main__":
    result = run_minimal_vertical_slice()
    print(json.dumps(result, indent=2))
