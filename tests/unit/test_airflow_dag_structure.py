from pathlib import Path

import pytest

pytest.importorskip("airflow")
DagBag = pytest.importorskip("airflow.models.dagbag").DagBag
dag_module = pytest.importorskip("pipelines.airflow_dags.audience_engine_dags")

ROOT = Path(__file__).resolve().parents[2]


def _expected_chain() -> list[str]:
    return [
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
        "execute_delivery",
    ]


def _assert_chain(dag) -> None:
    expected_chain = _expected_chain()
    assert set(expected_chain).issubset(set(dag.task_ids))
    for upstream, downstream in zip(expected_chain, expected_chain[1:]):
        assert downstream in dag.task_dict[upstream].downstream_task_ids


def test_operator_main_dag_structure():
    dag_bag = DagBag(
        dag_folder=str(ROOT / "pipelines" / "airflow_dags"),
        include_examples=False,
    )
    assert not dag_bag.import_errors, dag_bag.import_errors

    dag = dag_bag.get_dag("audience_engine_operator_main")
    assert dag is not None
    _assert_chain(dag)


def test_legacy_internal_dag_is_present_but_deemphasized():
    dag_bag = DagBag(
        dag_folder=str(ROOT / "pipelines" / "airflow_dags"),
        include_examples=False,
    )
    assert not dag_bag.import_errors, dag_bag.import_errors

    dag = dag_bag.get_dag("audience_engine_minimal_slice_e2e")
    assert dag is not None
    assert dag.schedule_interval is None
    assert "legacy" in dag.tags
    _assert_chain(dag)


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


def test_airflow_execute_delivery_task_calls_delivery_runner(monkeypatch, tmp_path):
    payload = {
        "versions": {"run_id": "e0f62885-0dbc-4d53-b1d5-59fd0be558e2"},
        "operations": {"delivery_target_id": "crm_postgres_outbox"},
        "status": "ok",
    }
    captured = {}

    monkeypatch.setattr(dag_module, "_require_payload", lambda task_id: payload)
    monkeypatch.setattr(
        dag_module,
        "get_current_context",
        lambda: {"run_id": "manual_delivery_1"},
    )
    monkeypatch.setattr(dag_module, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(
        dag_module.delivery_runner,
        "execute_delivery_for_run",
        lambda **kwargs: {
            **kwargs,
            "delivery_job_id": "6bf66314-d6f5-4fcb-ae0d-f4ff84ff4bd3",
            "status": "delivered",
        },
    )
    monkeypatch.setattr(
        dag_module,
        "_append_airflow_run_event",
        lambda summary, operation_context: captured.update(
            {"summary": summary, "operation_context": operation_context}
        ),
    )

    result = dag_module.task_execute_delivery()
    assert result["delivery"]["delivery_target_id"] == "crm_postgres_outbox"
    assert result["delivery"]["status"] == "delivered"
    assert captured["operation_context"]["delivery_target_id"] == "crm_postgres_outbox"
