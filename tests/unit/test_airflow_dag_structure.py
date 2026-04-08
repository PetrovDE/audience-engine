from pathlib import Path

import pytest

pytest.importorskip("airflow")
DagBag = pytest.importorskip("airflow.models.dagbag").DagBag
dag_module = pytest.importorskip("pipelines.airflow_dags.audience_engine_dags")

ROOT = Path(__file__).resolve().parents[2]


def test_minimal_slice_e2e_dag_structure():
    dag_bag = DagBag(
        dag_folder=str(ROOT / "pipelines" / "airflow_dags"),
        include_examples=False,
    )
    assert not dag_bag.import_errors, dag_bag.import_errors

    dag = dag_bag.get_dag("audience_engine_minimal_slice_e2e")
    assert dag is not None

    expected_chain = [
        "prepare_context",
        "seed_and_validate_raw",
        "build_feature_mart",
        "build_embeddings",
        "build_generation",
        "validate_generation",
        "promote_alias",
        "retrieve_candidates",
        "policy_gate",
        "export_and_audit",
    ]
    assert set(expected_chain).issubset(set(dag.task_ids))
    for upstream, downstream in zip(expected_chain, expected_chain[1:]):
        assert downstream in dag.task_dict[upstream].downstream_task_ids


def test_airflow_validate_generation_uses_lifecycle_service(monkeypatch, tmp_path):
    payload = {
        "paths": {"embeddings_path": str(tmp_path / "embeddings.jsonl")},
        "index_build": {"collection": "customers_v1", "alias": "audience-serving"},
    }
    captured = {}

    monkeypatch.setattr(dag_module, "_require_payload", lambda task_id: payload)
    monkeypatch.setattr(
        dag_module,
        "get_current_context",
        lambda: {"run_id": "manual_1"},
    )

    def _validate_latest(actor, embeddings_path):
        captured["actor_id"] = actor.actor_id
        captured["role"] = actor.role
        return {
            "stage": "validate_generation",
            "alias": "audience-serving",
            "collection": "customers_v1",
        }

    monkeypatch.setattr(
        dag_module.lifecycle_service,
        "validate_latest",
        _validate_latest,
    )

    result = dag_module.task_validate_generation()
    assert result["index_validation"]["stage"] == "validate_generation"
    assert captured["actor_id"] == "system:airflow:manual_1"
    assert captured["role"] == "system_internal"


def test_airflow_promote_alias_uses_lifecycle_service(monkeypatch):
    payload = {"index_validation": {"stage": "validate_generation"}}
    captured = {}

    monkeypatch.setattr(dag_module, "_require_payload", lambda task_id: payload)
    monkeypatch.setattr(
        dag_module,
        "get_current_context",
        lambda: {"run_id": "scheduled_2026_04_08"},
    )

    def _promote_latest(actor):
        captured["actor_id"] = actor.actor_id
        captured["role"] = actor.role
        return {
            "stage": "promote_alias",
            "alias": "audience-serving",
            "collection": "customers_v1",
        }

    monkeypatch.setattr(
        dag_module.lifecycle_service,
        "promote_latest",
        _promote_latest,
    )

    result = dag_module.task_promote_alias()
    assert result["index_promote"]["stage"] == "promote_alias"
    assert captured["actor_id"] == "system:airflow:scheduled_2026_04_08"
    assert captured["role"] == "system_internal"
