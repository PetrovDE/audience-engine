from pathlib import Path

import pytest

from pipelines.minimal_slice import lifecycle_service
from pipelines.minimal_slice.lifecycle_service import LifecycleActor


def _actor() -> LifecycleActor:
    return LifecycleActor(role="admin_operator", actor_id="admin:test")


def test_validate_latest_records_success_audit(monkeypatch):
    audit_calls = []
    monkeypatch.setattr(
        lifecycle_service,
        "get_latest_generation",
        lambda status: {
            "alias_name": "audience-serving",
            "collection_name": "customers_v1",
        },
    )
    monkeypatch.setattr(
        lifecycle_service,
        "validate_latest_generation",
        lambda embeddings_path: {
            "stage": "validate_generation",
            "alias": "audience-serving",
            "collection": "customers_v1",
            "checks": {"actual_count": 10},
        },
    )
    monkeypatch.setattr(
        lifecycle_service,
        "record_lifecycle_action",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    result = lifecycle_service.validate_latest(
        actor=_actor(),
        embeddings_path=Path("embeddings.jsonl"),
    )

    assert result["stage"] == "validate_generation"
    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == "validate_generation"
    assert audit_calls[0]["outcome"] == "success"


def test_validate_latest_records_failure_audit(monkeypatch):
    audit_calls = []
    monkeypatch.setattr(
        lifecycle_service,
        "get_latest_generation",
        lambda status: {
            "alias_name": "audience-serving",
            "collection_name": "customers_v1",
        },
    )

    def _boom(embeddings_path):
        raise ValueError("no built generation found")

    monkeypatch.setattr(lifecycle_service, "validate_latest_generation", _boom)
    monkeypatch.setattr(
        lifecycle_service,
        "record_lifecycle_action",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    with pytest.raises(ValueError, match="no built generation found"):
        lifecycle_service.validate_latest(
            actor=_actor(),
            embeddings_path=Path("embeddings.jsonl"),
        )

    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == "validate_generation"
    assert audit_calls[0]["outcome"] == "failed"
    assert "no built generation found" in audit_calls[0]["details"]["error"]


def test_promote_and_rollback_flow_records_audit(monkeypatch):
    audit_calls = []
    latest_states = {
        "validated": {
            "alias_name": "audience-serving",
            "collection_name": "customers_v2",
        },
        "promoted": {
            "alias_name": "audience-serving",
            "collection_name": "customers_v2",
            "previous_collection_name": "customers_v1",
        },
    }
    monkeypatch.setattr(
        lifecycle_service,
        "get_latest_generation",
        lambda status: latest_states[status],
    )
    monkeypatch.setattr(
        lifecycle_service,
        "promote_latest_generation",
        lambda: {
            "stage": "promote_alias",
            "alias": "audience-serving",
            "collection": "customers_v2",
            "previous_collection": "customers_v1",
        },
    )
    monkeypatch.setattr(
        lifecycle_service,
        "rollback_latest_alias",
        lambda: {
            "stage": "rollback_alias",
            "alias": "audience-serving",
            "collection": "customers_v1",
            "rolled_back_from": "customers_v2",
        },
    )
    monkeypatch.setattr(
        lifecycle_service,
        "record_lifecycle_action",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    promote_result = lifecycle_service.promote_latest(actor=_actor())
    rollback_result = lifecycle_service.rollback_latest(actor=_actor())

    assert promote_result["stage"] == "promote_alias"
    assert rollback_result["stage"] == "rollback_alias"
    assert [call["action"] for call in audit_calls] == [
        "promote_alias",
        "rollback_alias",
    ]
    assert all(call["outcome"] == "success" for call in audit_calls)
