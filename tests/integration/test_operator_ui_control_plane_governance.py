from __future__ import annotations

import re
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
import pytest

from services.retrieval_api import app as app_module
from services.retrieval_api import operator_control_plane_governance as control_plane_governance
from services.retrieval_api import operator_control_plane_management as control_plane_mgmt
from services.retrieval_api import operator_control_plane_ui as control_plane_ui

client = TestClient(app_module.app)

CAMPAIGN_KEY = "campaign-test-key"
ADMIN_KEY = "admin-test-key"
OPERATOR_UI_USERNAME = "admin"
OPERATOR_UI_PASSWORD = "203217"
VERSION_ID = "ad7f34f3-54d3-4caf-b603-ff3f064adb3d"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE_CAMPAIGN_API_KEYS", CAMPAIGN_KEY)
    monkeypatch.setenv("AE_ADMIN_API_KEYS", ADMIN_KEY)
    monkeypatch.setenv("OPERATOR_UI_USERNAME", OPERATOR_UI_USERNAME)
    monkeypatch.setenv("OPERATOR_UI_PASSWORD", OPERATOR_UI_PASSWORD)
    client.cookies.clear()


def _login() -> None:
    response = client.post(
        "/operator/login",
        data={
            "username": OPERATOR_UI_USERNAME,
            "password": OPERATOR_UI_PASSWORD,
            "next": "/operator/control-plane/versions",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _row(state: str = "validated") -> dict[str, object]:
    return {
        "version_id": VERSION_ID,
        "entity_key": "fs_credit",
        "version": "fs_credit_v2",
        "lifecycle_state": state,
        "payload": {"owner": "risk-team"},
    }


def test_operator_nav_persistently_includes_control_plane_versions(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        app_module.control_plane,
        "list_recent_run_events",
        lambda limit=20: [],
    )

    _login()
    response = client.get("/operator/recent-runs")

    assert response.status_code == 200
    assert 'href="/operator/control-plane/versions"' in response.text
    assert "Control-Plane Versions" in response.text


def test_detail_page_renders_promotion_readiness_panel(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(control_plane_mgmt, "load_version_detail", lambda **kwargs: _row())
    monkeypatch.setattr(
        control_plane_mgmt.control_plane_registry,
        "get_active_version",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        control_plane_mgmt,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        control_plane_mgmt,
        "promotion_governance_context",
        lambda **kwargs: {
            "promotion_readiness": {
                "target_state": "active",
                "promotion_ready": False,
                "evidence_count": 1,
                "blockers": [
                    {"code": "missing_readiness_result", "message": "Readiness missing."}
                ],
                "non_blocking": [],
                "checks": [],
            },
            "promotion_evidence_rows": [],
            "promotion_decision_rows": [],
            "promotion_evidence_types": (
                "validation_result",
                "readiness_result",
                "compatibility_check",
                "operator_note",
            ),
        },
    )

    _login()
    response = client.get(
        "/operator/control-plane/versions/feature_sets/fs_credit/"
        f"{VERSION_ID}",
    )

    assert response.status_code == 200
    assert "Promotion Governance Readiness" in response.text
    assert "Readiness missing." in response.text
    assert "Record Promotion Evidence" in response.text


def test_detail_page_for_current_active_version_marks_activation_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
):
    active_row = _row(state="active")
    monkeypatch.setattr(
        control_plane_mgmt,
        "load_version_detail",
        lambda **kwargs: active_row,
    )
    monkeypatch.setattr(
        control_plane_mgmt.control_plane_registry,
        "get_active_version",
        lambda **kwargs: active_row,
    )
    monkeypatch.setattr(
        control_plane_mgmt,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        control_plane_governance,
        "list_promotion_evidence",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        control_plane_governance,
        "list_recent_promotion_decisions",
        lambda **kwargs: [],
    )

    _login()
    response = client.get(
        "/operator/control-plane/versions/feature_sets/fs_credit/"
        f"{VERSION_ID}",
    )

    assert response.status_code == 200
    assert "already current active" in response.text
    assert "missing_validation_result" not in response.text
    assert "missing_readiness_result" not in response.text
    assert "not applicable (already current active)" in response.text
    assert re.search(
        r'actions/activate".*?<button[^>]*disabled[^>]*>\s*Activate\s*</button>',
        response.text,
        re.S,
    )


def test_evidence_submit_records_operator_evidence(monkeypatch: pytest.MonkeyPatch):
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        control_plane_ui,
        "record_promotion_evidence",
        lambda **kwargs: captured.append(kwargs),
    )

    _login()
    response = client.post(
        "/operator/control-plane/versions/feature_sets/fs_credit/"
        f"{VERSION_ID}/evidence",
        data={
            "evidence_type": "operator_note",
            "status": "info",
            "note": "manual signoff by operator",
            "details_json": '{"ticket":"AE-123"}',
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert captured
    assert captured[0]["evidence_type"] == "operator_note"
    assert captured[0]["status"] == "info"
    assert captured[0]["details"] == {"ticket": "AE-123"}


def test_activation_blocked_when_governance_has_blockers(monkeypatch: pytest.MonkeyPatch):
    captured_decisions: list[dict[str, object]] = []
    captured_audit: list[dict[str, object]] = []
    monkeypatch.setattr(control_plane_ui, "load_version_detail", lambda **kwargs: _row())
    monkeypatch.setattr(
        control_plane_ui,
        "evaluate_activation_governance",
        lambda **kwargs: {
            "promotion_ready": False,
            "blockers": [
                {
                    "code": "missing_readiness_result",
                    "message": "Readiness result evidence is missing.",
                }
            ],
        },
    )
    monkeypatch.setattr(
        control_plane_ui,
        "record_promotion_decision",
        lambda **kwargs: captured_decisions.append(kwargs) or {"decision_id": "d-1"},
    )
    monkeypatch.setattr(
        control_plane_ui.control_plane_registry,
        "transition_version_state",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not transition")),
    )
    monkeypatch.setattr(
        control_plane_ui,
        "record_registry_lifecycle_action",
        lambda **kwargs: captured_audit.append(kwargs),
    )
    monkeypatch.setattr(
        control_plane_ui,
        "render_detail_page",
        lambda **kwargs: HTMLResponse("blocked", status_code=400),
    )

    _login()
    response = client.post(
        "/operator/control-plane/versions/feature_sets/fs_credit/"
        f"{VERSION_ID}/actions/activate"
    )

    assert response.status_code == 400
    assert captured_decisions
    assert captured_decisions[0]["outcome"] == "blocked"
    assert captured_audit
    assert captured_audit[0]["outcome"] == "failed"


def test_activation_allowed_when_governance_ready(monkeypatch: pytest.MonkeyPatch):
    captured_transition: list[dict[str, str]] = []
    captured_decisions: list[dict[str, object]] = []
    captured_audit: list[dict[str, object]] = []
    monkeypatch.setattr(control_plane_ui, "load_version_detail", lambda **kwargs: _row())
    monkeypatch.setattr(
        control_plane_ui,
        "evaluate_activation_governance",
        lambda **kwargs: {
            "promotion_ready": True,
            "blockers": [],
            "non_blocking": [],
        },
    )

    def _transition(**kwargs):
        captured_transition.append(kwargs)
        return {
            "version_id": VERSION_ID,
            "entity_key": "fs_credit",
            "version": "fs_credit_v2",
            "lifecycle_state": "active",
            "payload": {},
        }

    monkeypatch.setattr(
        control_plane_ui.control_plane_registry,
        "transition_version_state",
        _transition,
    )
    monkeypatch.setattr(
        control_plane_ui,
        "record_promotion_decision",
        lambda **kwargs: captured_decisions.append(kwargs) or {"decision_id": "d-2"},
    )
    monkeypatch.setattr(
        control_plane_ui,
        "record_registry_lifecycle_action",
        lambda **kwargs: captured_audit.append(kwargs),
    )

    _login()
    response = client.post(
        "/operator/control-plane/versions/feature_sets/fs_credit/"
        f"{VERSION_ID}/actions/activate",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert captured_transition
    assert captured_transition[0]["target_state"] == "active"
    assert captured_decisions
    assert captured_decisions[0]["outcome"] == "success"
    assert captured_audit
    details = captured_audit[0]["details"]
    assert details["governance_decision_id"] == "d-2"
