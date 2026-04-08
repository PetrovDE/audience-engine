from pathlib import Path

import pytest

pytest.importorskip("airflow")
DagBag = pytest.importorskip("airflow.models.dagbag").DagBag

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
