import pytest
from fastapi.testclient import TestClient

from services.retrieval_api import app as app_module
from services.retrieval_api import operator_control_plane_management as control_plane_mgmt_module
from services.retrieval_api import operator_control_plane_ui as control_plane_ui_module

client = TestClient(app_module.app)

CAMPAIGN_KEY = "campaign-test-key"
ADMIN_KEY = "admin-test-key"
OPERATOR_UI_USERNAME = "admin"
OPERATOR_UI_PASSWORD = "203217"
VERSION_ID = "ad7f34f3-54d3-4caf-b603-ff3f064adb3d"
ACTIVE_ID = "c4c5f52d-ec77-4fa8-8963-03de9ad89866"

@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
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
    cookie_header = response.headers.get("set-cookie", "")
    assert "ae_operator_session=" in cookie_header


def _row(
    *,
    entity_key: str = "fs_credit",
    version: str = "fs_credit_v2",
    version_id: str = VERSION_ID,
    lifecycle_state: str = "draft",
    payload: dict | None = None,
    **extra,
) -> dict:
    result = {
        "version_id": version_id,
        "entity_key": entity_key,
        "version": version,
        "lifecycle_state": lifecycle_state,
        "payload": payload if isinstance(payload, dict) else {},
    }
    result.update(extra)
    return result


@pytest.mark.parametrize(
    (
        "entity_type",
        "entity_key",
        "version",
        "expected_label",
        "expected_registry_entity_type",
    ),
    [
        (
            "feature_sets",
            "fs_credit",
            "fs_credit_v2",
            "Feature Set Versions",
            "feature_sets",
        ),
        ("models", "model_embed", "nomic-embed-text", "Model Versions", "models"),
        (
            "embedding_model_versions",
            "local_ollama",
            "emb_provider_nomic_v2",
            "Embedding Model Versions",
            "embedding_providers",
        ),
        ("policies", "policy_credit", "policy_credit_v2", "Policy Versions", "policies"),
        (
            "audience_definitions",
            "audience_default",
            "aud_default_v2",
            "Audience Definition Versions",
            "audience_definitions",
        ),
    ],
)
def test_operator_control_plane_list_renders_family_rows(
    monkeypatch,
    entity_type: str,
    entity_key: str,
    version: str,
    expected_label: str,
    expected_registry_entity_type: str,
):
    row = _row(
        entity_key=entity_key,
        version=version,
        lifecycle_state="active",
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [
            row
        ]
        if kwargs["entity_type"] == expected_registry_entity_type
        else [],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: row if kwargs.get("entity_key") == entity_key else None,
    )
    monkeypatch.setattr(
        control_plane_mgmt_module,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [],
    )

    _login()
    response = client.get(
        f"/operator/control-plane/versions?entity_type={entity_type}&entity_key={entity_key}"
    )

    assert response.status_code == 200
    assert expected_label in response.text
    assert entity_key in response.text
    assert version in response.text
    assert 'data-current="yes"' in response.text


def test_operator_control_plane_detail_shows_metadata_and_active_visibility(monkeypatch):
    provider_row = _row(
        entity_key="local_ollama",
        version="emb_provider_nomic_v2",
        lifecycle_state="active",
        payload={
            "provider_type": "ollama",
            "provider_config_ref": "OLLAMA_BASE_URL",
            "model_version": "nomic-embed-text",
        },
        provider_model_ref="nomic-embed-text",
        model_version_id="7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79",
        capability="embedding",
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [provider_row],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: provider_row,
    )
    monkeypatch.setattr(
        control_plane_mgmt_module,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [
            {
                "action": "activate",
                "target_state": "active",
                "outcome": "success",
                "actor_id": "operator_ui:admin",
                "details": {"from_state": "validated", "to_state": "active"},
            }
        ],
    )

    _login()
    response = client.get(
        "/operator/control-plane/versions/embedding_model_versions/local_ollama/"
        f"{VERSION_ID}"
    )

    assert response.status_code == 200
    assert "Current active" in response.text
    assert "provider_model_ref" in response.text
    assert "nomic-embed-text" in response.text
    assert "model_version_id" in response.text
    assert "activate" in response.text


def test_operator_control_plane_embedding_model_action_submit_uses_registry_transition(
    monkeypatch,
):
    current = _row(
        entity_key="local_ollama",
        version="emb_provider_nomic_v2",
        lifecycle_state="draft",
        payload={"provider_type": "ollama"},
        provider_model_ref="nomic-embed-text",
        capability="embedding",
    )
    captured_transition: dict[str, str] = {}
    captured_audit: list[dict[str, str]] = []

    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [current],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: None,
    )

    def _transition(**kwargs):
        captured_transition.update(kwargs)
        return _row(
            entity_key=current["entity_key"],
            version=current["version"],
            version_id=current["version_id"],
            lifecycle_state=kwargs["target_state"],
            payload=current["payload"],
            provider_model_ref=current["provider_model_ref"],
            capability=current["capability"],
        )

    monkeypatch.setattr(
        app_module.control_plane_registry,
        "transition_version_state",
        _transition,
    )
    monkeypatch.setattr(
        control_plane_ui_module,
        "record_registry_lifecycle_action",
        lambda **kwargs: captured_audit.append(kwargs),
    )

    _login()
    response = client.post(
        "/operator/control-plane/versions/embedding_model_versions/local_ollama/"
        f"{current['version_id']}/actions/validate",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert captured_transition == {
        "entity_type": "embedding_providers",
        "version_id": VERSION_ID,
        "target_state": "validated",
    }
    assert captured_audit
    assert captured_audit[0]["entity_type"] == "embedding_model_versions"
    assert captured_audit[0]["action"] == "validate"
    assert captured_audit[0]["target_state"] == "validated"
    assert captured_audit[0]["outcome"] == "success"


def test_operator_control_plane_action_submit_delegates_to_registry_transition(
    monkeypatch,
):
    current = _row(lifecycle_state="draft")
    captured_transition: dict[str, str] = {}
    captured_audit: list[dict[str, str]] = []

    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [current],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: None,
    )

    def _transition(**kwargs):
        captured_transition.update(kwargs)
        return _row(
            entity_key=current["entity_key"],
            version=current["version"],
            version_id=current["version_id"],
            lifecycle_state=kwargs["target_state"],
        )

    monkeypatch.setattr(
        app_module.control_plane_registry,
        "transition_version_state",
        _transition,
    )
    monkeypatch.setattr(
        control_plane_ui_module,
        "record_registry_lifecycle_action",
        lambda **kwargs: captured_audit.append(kwargs),
    )

    _login()
    response = client.post(
        f"/operator/control-plane/versions/feature_sets/{current['entity_key']}/"
        f"{current['version_id']}/actions/validate",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert captured_transition == {
        "entity_type": "feature_sets",
        "version_id": VERSION_ID,
        "target_state": "validated",
    }
    assert captured_audit
    assert captured_audit[0]["action"] == "validate"
    assert captured_audit[0]["target_state"] == "validated"
    assert captured_audit[0]["outcome"] == "success"


def test_operator_control_plane_action_invalid_transition_is_blocked(monkeypatch):
    current = _row(lifecycle_state="draft")
    captured_audit: list[dict[str, str]] = []

    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [current],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "transition_version_state",
        lambda **kwargs: (_ for _ in ()).throw(
            ValueError("Invalid lifecycle transition: draft -> retired")
        ),
    )
    monkeypatch.setattr(
        control_plane_ui_module,
        "record_registry_lifecycle_action",
        lambda **kwargs: captured_audit.append(kwargs),
    )
    monkeypatch.setattr(
        control_plane_mgmt_module,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [],
    )

    _login()
    response = client.post(
        f"/operator/control-plane/versions/feature_sets/{current['entity_key']}/"
        f"{current['version_id']}/actions/retire"
    )

    assert response.status_code == 400
    assert "Invalid lifecycle transition" in response.text
    assert captured_audit
    assert captured_audit[0]["action"] == "retire"
    assert captured_audit[0]["outcome"] == "failed"


def test_operator_control_plane_list_marks_only_current_active_version(monkeypatch):
    active_row = _row(version_id=ACTIVE_ID, version="fs_credit_v1", lifecycle_state="active")
    older_row = _row(version_id=VERSION_ID, version="fs_credit_v2", lifecycle_state="validated")
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [active_row, older_row],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: active_row,
    )
    monkeypatch.setattr(
        control_plane_mgmt_module,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [],
    )

    _login()
    response = client.get(
        "/operator/control-plane/versions?entity_type=feature_sets&entity_key=fs_credit"
    )
    assert response.status_code == 200
    assert 'data-current="yes"' in response.text
    assert 'data-current="no"' in response.text
