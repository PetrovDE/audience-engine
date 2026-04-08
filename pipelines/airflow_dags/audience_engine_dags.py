"""Airflow DAG wiring for the real minimal-slice end-to-end pipeline."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator, get_current_context

from pipelines.minimal_slice.config import (
    EMBEDDING_MODEL_VERSION,
    FEATURE_MART_PATH,
    FEATURE_SLICE_SOURCE,
    SUMMARY_PATH,
)
from pipelines.minimal_slice.data_quality import (
    validate_embeddings_artifact,
    validate_feature_mart_contract,
    validate_raw_contract,
)
from pipelines.minimal_slice.embedding import (
    build_embeddings,
    read_embeddings_emb_version,
)
from pipelines.minimal_slice.exporter import export_approved
from pipelines.minimal_slice.feature_mart import build_feature_mart_snapshot
from pipelines.minimal_slice.policy_engine import evaluate_policy
from pipelines.minimal_slice.qdrant_index import (
    build_generation,
    promote_alias,
    validate_generation,
)
from pipelines.minimal_slice.retrieval import retrieve_similar
from pipelines.minimal_slice.run_flow import (
    _build_and_validate_bundle,
    _build_audit_rows,
    _build_policy_input,
    _write_audit_to_postgres,
)
from pipelines.minimal_slice.storage import minio_is_configured, upload_export_to_minio
from pipelines.minimal_slice.synthetic_data import generate_synthetic_data
from pipelines.version_bundle import VersionBundle

ROOT = Path(
    os.getenv("AUDIENCE_ENGINE_ROOT", str(Path(__file__).resolve().parents[2]))
).resolve()


def _require_payload(task_id: str) -> dict[str, Any]:
    ctx = get_current_context()
    ti = ctx["ti"]
    payload = ti.xcom_pull(task_ids=task_id)
    if not isinstance(payload, dict):
        raise ValueError(f"Missing or invalid XCom payload from task {task_id!r}")
    return payload


def _default_args() -> dict[str, Any]:
    return {"owner": "audience-engine", "depends_on_past": False}


def task_prepare_context() -> dict[str, Any]:
    ctx = get_current_context()
    dag_run = ctx.get("dag_run")
    conf = dag_run.conf if dag_run and dag_run.conf else {}
    campaign_id = conf.get("campaign_id") or f"airflow-{ctx.get('run_id', 'manual')}"
    bundle = _build_and_validate_bundle(campaign_id=campaign_id)
    return {
        "bundle": bundle.__dict__,
        "quality_checks": [],
    }


def task_seed_and_validate_raw() -> dict[str, Any]:
    payload = _require_payload("prepare_context")
    generated = generate_synthetic_data(customer_count=200, seed=7)
    raw_path = Path(generated["raw"])
    payload["quality_checks"].append(validate_raw_contract(raw_path))
    payload["paths"] = {
        "raw_path": str(raw_path),
        "blacklist_path": str(generated["blacklist"]),
        "comm_history_path": str(generated["comm_history"]),
    }
    return payload


def task_build_feature_mart() -> dict[str, Any]:
    payload = _require_payload("seed_and_validate_raw")
    bundle = payload["bundle"]
    raw_path = Path(payload["paths"]["raw_path"])
    feature_mart_path = build_feature_mart_snapshot(
        raw_path=raw_path,
        output_path=FEATURE_MART_PATH,
        source_mode=FEATURE_SLICE_SOURCE,
        run_id=bundle["run_id"],
    )
    payload["quality_checks"].append(validate_feature_mart_contract(feature_mart_path))
    payload["paths"]["feature_mart_path"] = str(feature_mart_path)
    return payload


def task_build_embeddings() -> dict[str, Any]:
    payload = _require_payload("build_feature_mart")
    bundle = payload["bundle"]
    feature_mart_path = Path(payload["paths"]["feature_mart_path"])
    embeddings_path, vector_size = build_embeddings(
        feature_mart_path=feature_mart_path,
        ollama_model=EMBEDDING_MODEL_VERSION,
    )
    payload["quality_checks"].append(
        validate_embeddings_artifact(
            embeddings_path=embeddings_path,
            expected_emb_version=bundle["emb_version"],
        )
    )
    runtime_emb_version = read_embeddings_emb_version(embeddings_path)
    if runtime_emb_version != bundle["emb_version"]:
        raise ValueError(
            "Embedding lineage mismatch at runtime: "
            f"bundle.emb_version={bundle['emb_version']!r}, "
            f"runtime.emb_version={runtime_emb_version!r}"
        )
    payload["paths"]["embeddings_path"] = str(embeddings_path)
    payload["vector_size"] = int(vector_size)
    return payload


def task_build_generation() -> dict[str, Any]:
    payload = _require_payload("build_embeddings")
    bundle = payload["bundle"]
    build_meta = build_generation(
        embeddings_path=Path(payload["paths"]["embeddings_path"]),
        vector_size=int(payload["vector_size"]),
        alias_name_override=bundle["index_alias"],
        collection_name_override=bundle["concrete_qdrant_collection"],
    )
    payload["index_build"] = build_meta
    return payload


def task_validate_generation() -> dict[str, Any]:
    payload = _require_payload("build_generation")
    build_meta = payload["index_build"]
    validation = validate_generation(
        embeddings_path=Path(payload["paths"]["embeddings_path"]),
        collection_name=build_meta["collection"],
        alias_name=build_meta["alias"],
        expected_count=build_meta["points_count"],
    )
    payload["index_validation"] = validation
    return payload


def task_promote_alias() -> dict[str, Any]:
    payload = _require_payload("validate_generation")
    build_meta = payload["index_build"]
    payload["index_promote"] = promote_alias(
        alias_name=build_meta["alias"],
        collection_name=build_meta["collection"],
    )
    return payload


def task_retrieve_candidates() -> dict[str, Any]:
    payload = _require_payload("promote_alias")
    bundle = payload["bundle"]
    query_customer = "cust_00000"
    retrieved = retrieve_similar(
        top_k=50,
        query_customer_id=query_customer,
        product_line="credit_card",
        region_codes=["us_west", "us_central", "us_east"],
        segment_ids=["mass", "affluent", "student", "smb"],
        min_tenure_months=3,
        max_delinquency_12m_count=2,
        fs_version=bundle["fs_version"],
        emb_version=bundle["emb_version"],
        policy_version=bundle["policy_version"],
    )
    payload["query_customer_id"] = query_customer
    payload["retrieved"] = retrieved
    return payload


def task_policy_gate() -> dict[str, Any]:
    payload = _require_payload("retrieve_candidates")
    bundle = payload["bundle"]
    policy_result = evaluate_policy(
        candidates=_build_policy_input(payload["retrieved"]),
        policy_version=bundle["policy_version"],
        blacklist_path=Path(payload["paths"]["blacklist_path"]),
        comm_history_path=Path(payload["paths"]["comm_history_path"]),
        campaign_id=bundle["campaign_id"],
        requested_size=20,
    )
    payload["policy_result"] = policy_result
    return payload


def task_export_and_audit() -> dict[str, Any]:
    payload = _require_payload("policy_gate")
    bundle = VersionBundle(**payload["bundle"])
    index_meta = payload["index_promote"]
    policy_result = payload["policy_result"]
    retrieved = payload["retrieved"]

    export_ready = {
        **policy_result,
        "results": [
            row for row in policy_result["results"] if row.get("selected", False)
        ],
    }
    export_path = export_approved(
        policy_result=export_ready,
        output_path=ROOT / "data" / "minimal_slice" / "run" / "approved_audience.jsonl",
    )
    export_minio_uri = (
        upload_export_to_minio(export_path=export_path, run_id=bundle.run_id)
        if minio_is_configured()
        else None
    )

    run_ts = datetime.now(timezone.utc).isoformat()
    run_row, selected_rows, rejection_rows, decision_rows = _build_audit_rows(
        retrieved=retrieved,
        policy_result=policy_result,
        bundle=bundle,
        run_ts=run_ts,
        product_id="minimal_slice_airflow",
        channel="email",
        resolved_collection=index_meta["collection"],
    )
    _write_audit_to_postgres(
        run_row=run_row,
        selected_rows=selected_rows,
        rejection_rows=rejection_rows,
        decision_rows=decision_rows,
    )

    summary = {
        "run_ts": run_ts,
        "status": "ok",
        "versions": run_row["version_bundle"],
        "inputs": payload["paths"],
        "quality": {
            "status": "passed",
            "checks": payload["quality_checks"],
        },
        "index": index_meta,
        "retrieval": {
            "query_customer_id": payload["query_customer_id"],
            "retrieved_count": len(retrieved),
        },
        "policy": policy_result["summary"],
        "export_path": str(export_path),
        "export_minio_uri": export_minio_uri,
        "audit": {
            "postgres": {
                "run_table": "audience_run",
                "selected_rows_written": len(selected_rows),
                "rejection_summary_rows_written": len(rejection_rows),
                "policy_decision_rows_written": len(decision_rows),
            }
        },
    }

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


with DAG(
    dag_id="audience_engine_minimal_slice_e2e",
    default_args=_default_args(),
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["audience-engine", "minimal-slice", "e2e"],
) as audience_engine_minimal_slice_e2e:
    prepare_context = PythonOperator(
        task_id="prepare_context",
        python_callable=task_prepare_context,
    )
    seed_and_validate_raw = PythonOperator(
        task_id="seed_and_validate_raw",
        python_callable=task_seed_and_validate_raw,
    )
    build_feature_mart_task = PythonOperator(
        task_id="build_feature_mart",
        python_callable=task_build_feature_mart,
    )
    build_embeddings_task = PythonOperator(
        task_id="build_embeddings",
        python_callable=task_build_embeddings,
    )
    build_generation_task = PythonOperator(
        task_id="build_generation",
        python_callable=task_build_generation,
    )
    validate_generation_task = PythonOperator(
        task_id="validate_generation",
        python_callable=task_validate_generation,
    )
    promote_alias_task = PythonOperator(
        task_id="promote_alias",
        python_callable=task_promote_alias,
    )
    retrieve_candidates_task = PythonOperator(
        task_id="retrieve_candidates",
        python_callable=task_retrieve_candidates,
    )
    policy_gate_task = PythonOperator(
        task_id="policy_gate",
        python_callable=task_policy_gate,
    )
    export_and_audit_task = PythonOperator(
        task_id="export_and_audit",
        python_callable=task_export_and_audit,
    )

    prepare_context >> seed_and_validate_raw >> build_feature_mart_task
    build_feature_mart_task >> build_embeddings_task >> build_generation_task
    build_generation_task >> validate_generation_task >> promote_alias_task
    promote_alias_task >> retrieve_candidates_task >> policy_gate_task
    policy_gate_task >> export_and_audit_task
