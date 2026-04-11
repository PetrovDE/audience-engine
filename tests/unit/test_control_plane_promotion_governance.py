from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.minimal_slice import control_plane_promotion_governance as governance


@pytest.fixture
def isolated_audit_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        governance,
        "PROMOTION_EVIDENCE_PATH",
        tmp_path / "promotion_evidence.jsonl",
    )
    monkeypatch.setattr(
        governance,
        "PROMOTION_DECISION_AUDIT_PATH",
        tmp_path / "promotion_decision_audit.jsonl",
    )


def _version_row(state: str = "validated", **extra: str) -> dict[str, str]:
    row = {"lifecycle_state": state}
    row.update(extra)
    return row


def _record_required_evidence(
    *,
    entity_type: str = "feature_sets",
    entity_key: str = "fs_credit",
    version_id: str = "v-1",
) -> None:
    governance.record_promotion_evidence(
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        evidence_type="validation_result",
        status="pass",
        actor_id="operator_ui:admin",
    )
    governance.record_promotion_evidence(
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        evidence_type="readiness_result",
        status="ready",
        actor_id="operator_ui:admin",
    )


def test_evidence_record_and_filtered_list(isolated_audit_paths: None) -> None:
    governance.record_promotion_evidence(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        evidence_type="validation_result",
        status="pass",
        actor_id="operator_ui:admin",
        note="validation job #42 passed",
    )
    governance.record_promotion_evidence(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-2",
        evidence_type="validation_result",
        status="fail",
        actor_id="operator_ui:admin",
    )

    rows = governance.list_promotion_evidence(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        limit=10,
    )

    assert len(rows) == 1
    assert rows[0]["evidence_type"] == "validation_result"
    assert rows[0]["note"] == "validation job #42 passed"


def test_evaluate_promotion_reports_blockers_for_missing_required_evidence(
    isolated_audit_paths: None,
) -> None:
    evaluation = governance.evaluate_promotion_readiness(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        version_row=_version_row(state="validated"),
    )

    assert evaluation["promotion_ready"] is False
    blocker_codes = {row["code"] for row in evaluation["blockers"]}
    assert "missing_validation_result" in blocker_codes
    assert "missing_readiness_result" in blocker_codes
    non_blocking_codes = {row["code"] for row in evaluation["non_blocking"]}
    assert "missing_operator_note" in non_blocking_codes


def test_evaluate_promotion_ready_when_required_evidence_is_passing(
    isolated_audit_paths: None,
) -> None:
    _record_required_evidence(entity_type="feature_sets")
    governance.record_promotion_evidence(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        evidence_type="operator_note",
        status="info",
        actor_id="operator_ui:admin",
        note="risk accepted for minor docs lag",
    )

    evaluation = governance.evaluate_promotion_readiness(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        version_row=_version_row(state="validated"),
    )

    assert evaluation["promotion_ready"] is True
    assert evaluation["blockers"] == []
    assert evaluation["non_blocking"] == []


def test_embedding_promotion_evaluation_requires_compatibility_and_provider_refs(
    isolated_audit_paths: None,
) -> None:
    _record_required_evidence(
        entity_type="embedding_model_versions",
        entity_key="local_ollama",
        version_id="v-emb-1",
    )
    governance.record_promotion_evidence(
        entity_type="embedding_model_versions",
        entity_key="local_ollama",
        version_id="v-emb-1",
        evidence_type="compatibility_check",
        status="pass",
        actor_id="operator_ui:admin",
    )

    evaluation = governance.evaluate_promotion_readiness(
        entity_type="embedding_model_versions",
        entity_key="local_ollama",
        version_id="v-emb-1",
        version_row=_version_row(state="validated"),
    )

    assert evaluation["promotion_ready"] is False
    blocker_codes = {row["code"] for row in evaluation["blockers"]}
    assert "missing_provider_model_ref" in blocker_codes
    assert "missing_model_version_id" in blocker_codes


def test_lifecycle_transition_remains_a_blocker_for_draft_to_active(
    isolated_audit_paths: None,
) -> None:
    _record_required_evidence(entity_type="feature_sets")

    evaluation = governance.evaluate_promotion_readiness(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        version_row=_version_row(state="draft"),
    )

    assert evaluation["promotion_ready"] is False
    blocker_codes = {row["code"] for row in evaluation["blockers"]}
    assert "invalid_lifecycle_transition" in blocker_codes


def test_promotion_decision_audit_round_trip(isolated_audit_paths: None) -> None:
    decision = governance.record_promotion_decision(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        target_state="active",
        action="activate",
        outcome="blocked",
        actor_id="operator_ui:admin",
        evaluation={"promotion_ready": False},
        note="missing readiness evidence",
    )

    rows = governance.list_recent_promotion_decisions(
        entity_type="feature_sets",
        entity_key="fs_credit",
        version_id="v-1",
        limit=5,
    )

    assert len(rows) == 1
    assert rows[0]["decision_id"] == decision["decision_id"]
    assert rows[0]["outcome"] == "blocked"
