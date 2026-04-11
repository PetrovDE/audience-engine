from __future__ import annotations

import pytest
from fastapi.responses import HTMLResponse

from services.retrieval_api import app as app_module
from services.retrieval_api import operator_control_plane_management as control_plane_mgmt
from services.retrieval_api import operator_control_plane_ui as control_plane_ui
from tests.integration.operator_ui_uat_helpers import (
    VERSION_ID,
    apply_auth_env,
    client,
    login,
    patch_common_operator_catalog,
)


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_auth_env(monkeypatch)


def test_uat_pack_control_plane_governance_blocked_activation_journey(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    row = {
        "version_id": VERSION_ID,
        "entity_key": "fs_credit",
        "version": "fs_credit_v2",
        "lifecycle_state": "validated",
        "payload": {"owner": "risk-team"},
    }
    monkeypatch.setattr(control_plane_ui, "load_version_detail", lambda **kwargs: row)
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
        "render_detail_page",
        lambda **kwargs: HTMLResponse("blocked", status_code=400),
    )
    decisions: list[dict[str, object]] = []
    monkeypatch.setattr(
        control_plane_ui,
        "record_promotion_decision",
        lambda **kwargs: decisions.append(kwargs) or {"decision_id": "d-1"},
    )
    monkeypatch.setattr(
        control_plane_ui.control_plane_registry,
        "transition_version_state",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not transition")),
    )

    login("/operator/control-plane/versions")
    response = client.post(
        f"/operator/control-plane/versions/feature_sets/fs_credit/{VERSION_ID}/actions/activate"
    )

    assert response.status_code == 400
    assert decisions
    assert decisions[0]["outcome"] == "blocked"


def test_uat_pack_provider_model_visibility_journey(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    row = {
        "version_id": VERSION_ID,
        "entity_key": "local_ollama",
        "version": "emb_provider_nomic_v2",
        "lifecycle_state": "active",
        "payload": {
            "provider_type": "ollama",
            "provider_config_ref": "OLLAMA_BASE_URL",
            "model_version": "nomic-embed-text",
        },
        "provider_model_ref": "nomic-embed-text",
        "model_version_id": "7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79",
        "capability": "embedding",
    }
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [row] if kwargs.get("entity_type") == "embedding_providers" else [],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: row,
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
                "promotion_ready": True,
                "governance_applicability": "applicable",
                "blockers": [],
                "non_blocking": [],
                "checks": [],
                "evidence_count": 0,
            },
            "promotion_evidence_rows": [],
            "promotion_decision_rows": [],
            "promotion_evidence_types": ("operator_note",),
        },
    )

    login("/operator/control-plane/versions")
    listing = client.get(
        "/operator/control-plane/versions"
        "?entity_type=embedding_model_versions&entity_key=local_ollama"
    )
    assert listing.status_code == 200
    assert "Embedding Model Versions" in listing.text
    assert "emb_provider_nomic_v2" in listing.text

    detail = client.get(
        "/operator/control-plane/versions/embedding_model_versions/local_ollama/"
        f"{VERSION_ID}"
    )
    assert detail.status_code == 200
    assert "provider_model_ref" in detail.text
    assert "nomic-embed-text" in detail.text

    readiness = client.get("/operator/readiness")
    assert readiness.status_code == 200
    assert "Readiness Interpretation" in readiness.text
    assert "clickhouse_postgres_export" in readiness.text
