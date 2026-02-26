"""Airflow DAGs for Audience Engine minimal slice workflows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from airflow import DAG
from airflow.operators.python import PythonOperator

from pipelines.minimal_slice.config import EMBEDDINGS_PATH, FEATURE_MART_PATH, RAW_PATH
from pipelines.minimal_slice.embedding import build_embeddings
from pipelines.minimal_slice.feature_mart import build_feature_mart_snapshot
from pipelines.minimal_slice.qdrant_index import create_or_replace_index, switch_alias_to_blue


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = ROOT / "governance" / "contracts"


def _load_contract(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _validate_contract_rows(rows: list[dict[str, Any]], contract: dict[str, Any], dataset_name: str) -> None:
    if not rows:
        raise ValueError(f"{dataset_name} dataset is empty")

    required_fields = [
        field["name"]
        for field in contract.get("fields", [])
        if field.get("required", False)
    ]
    required_versions = contract.get("required_versions", [])

    missing_required: dict[str, int] = {}

    for field in required_fields + required_versions:
        missing_count = sum(1 for row in rows if field not in row or row[field] in (None, ""))
        if missing_count > 0:
            missing_required[field] = missing_count

    if missing_required:
        details = ", ".join(f"{k}: {v} rows" for k, v in sorted(missing_required.items()))
        raise ValueError(f"{dataset_name} contract failed. Missing required values -> {details}")


def run_data_contract_checks() -> None:
    raw_contract = _load_contract(CONTRACTS_DIR / "raw.yaml")
    feature_contract = _load_contract(CONTRACTS_DIR / "feature_mart.yaml")

    raw_rows = _read_jsonl(RAW_PATH)
    feature_rows = _read_jsonl(FEATURE_MART_PATH)

    _validate_contract_rows(raw_rows, raw_contract, "raw")
    _validate_contract_rows(feature_rows, feature_contract, "feature_mart")


def task_build_feature_mart() -> str:
    output = build_feature_mart_snapshot(raw_path=RAW_PATH)
    return str(output)


def task_build_embeddings() -> dict[str, Any]:
    path, vector_size = build_embeddings(feature_mart_path=FEATURE_MART_PATH)
    return {"embeddings_path": str(path), "vector_size": vector_size}


def _embedding_vector_size(embeddings_path: Path = EMBEDDINGS_PATH) -> int:
    rows = _read_jsonl(embeddings_path)
    if not rows:
        raise ValueError(f"No embeddings found at {embeddings_path}")
    vector = rows[0].get("vector")
    if not isinstance(vector, list) or not vector:
        raise ValueError(f"Invalid vector payload in {embeddings_path}")
    return len(vector)


def task_build_index_blue() -> dict[str, str]:
    vector_size = _embedding_vector_size(EMBEDDINGS_PATH)
    index_meta = create_or_replace_index(
        embeddings_path=EMBEDDINGS_PATH,
        vector_size=vector_size,
    )
    return index_meta


def task_switch_alias() -> dict[str, str]:
    return switch_alias_to_blue()


def _default_args() -> dict[str, Any]:
    return {"owner": "audience-engine", "depends_on_past": False}


with DAG(
    dag_id="build_feature_mart",
    default_args=_default_args(),
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["audience-engine", "feature-mart"],
) as build_feature_mart_dag:
    PythonOperator(task_id="build_feature_mart", python_callable=task_build_feature_mart)


with DAG(
    dag_id="build_embeddings",
    default_args=_default_args(),
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["audience-engine", "embeddings"],
) as build_embeddings_dag:
    PythonOperator(task_id="build_embeddings", python_callable=task_build_embeddings)


with DAG(
    dag_id="build_index_blue",
    default_args=_default_args(),
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["audience-engine", "index", "blue-green"],
) as build_index_blue_dag:
    PythonOperator(task_id="build_index_blue", python_callable=task_build_index_blue)


with DAG(
    dag_id="switch_alias",
    default_args=_default_args(),
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["audience-engine", "index", "alias"],
) as switch_alias_dag:
    PythonOperator(task_id="switch_alias", python_callable=task_switch_alias)


with DAG(
    dag_id="data_contract_checks",
    default_args=_default_args(),
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["audience-engine", "governance", "contracts"],
) as data_contract_checks_dag:
    PythonOperator(task_id="data_contract_checks", python_callable=run_data_contract_checks)
