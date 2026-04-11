import pytest
from fastapi.testclient import TestClient

from services.retrieval_api import app as app_module
from services.retrieval_api import operator_control_plane_management as control_plane_mgmt

client = TestClient(app_module.app)

CAMPAIGN_KEY = "campaign-test-key"
ADMIN_KEY = "admin-test-key"
OPERATOR_UI_USERNAME = "admin"
OPERATOR_UI_PASSWORD = "203217"
VERSION_ID = "4f00e0ea-18f1-4185-ae83-c6e774a9d60a"


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
            "next": "/operator/dashboard",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _patch_operator_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_module.control_plane,
        "load_operator_defaults",
        lambda: app_module.control_plane.OperatorDefaults(
            default_policy_version="policy_credit_v1",
            default_integration_profile_id="clickhouse_postgres_export",
            default_delivery_target_id="crm_postgres_outbox",
        ),
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_policies",
        lambda: [{"policy_version": "policy_credit_v1", "status": "active"}],
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_source_connectors",
        lambda include_planned=True: [
            {
                "source_id": "clickhouse_feature_slice",
                "implementation_status": "implemented",
            }
        ],
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_export_targets",
        lambda include_planned=True: [
            {
                "export_id": "postgres_export_table",
                "implementation_status": "implemented",
            }
        ],
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_integration_profiles",
        lambda include_planned=True: [
            {
                "profile_id": "clickhouse_postgres_export",
                "source_id": "clickhouse_feature_slice",
                "export_id": "postgres_export_table",
                "implementation_status": "implemented",
            },
            {
                "profile_id": "future_profile",
                "source_id": "future_source",
                "export_id": "future_export",
                "implementation_status": "planned",
            },
        ],
    )
    monkeypatch.setattr(
        app_module.integrations,
        "annotate_runtime_readiness",
        lambda sources, exports, profiles: {
            "sources": [
                {
                    "source_id": "clickhouse_feature_slice",
                    "implementation_status": "implemented",
                    "runtime_runnable": True,
                    "runtime_readiness_mode": "config_and_connectivity",
                    "runtime_validation_errors": [],
                }
            ],
            "exports": [
                {
                    "export_id": "postgres_export_table",
                    "implementation_status": "implemented",
                    "runtime_runnable": True,
                    "runtime_readiness_mode": "config_and_connectivity",
                    "runtime_validation_errors": [],
                }
            ],
            "profiles": [
                {
                    "profile_id": "clickhouse_postgres_export",
                    "implementation_status": "implemented",
                    "runtime_runnable": True,
                    "runtime_readiness_mode": "profile_config_and_connectivity",
                    "runtime_validation_errors": [],
                },
                {
                    "profile_id": "future_profile",
                    "implementation_status": "planned",
                    "runtime_runnable": False,
                    "runtime_readiness_mode": "not_implemented",
                    "runtime_validation_errors": [],
                },
            ],
        },
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_delivery_targets",
        lambda include_planned=True: [
            {
                "delivery_target_id": "crm_postgres_outbox",
                "implementation_status": "implemented",
                "runtime_runnable": True,
                "runtime_readiness_mode": "config_and_connectivity",
                "runtime_validation_errors": [],
            },
            {
                "delivery_target_id": "crm_api_future",
                "implementation_status": "planned",
                "runtime_runnable": False,
                "runtime_readiness_mode": "not_implemented",
                "runtime_validation_errors": [],
            },
        ],
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "describe_operational_model",
        lambda: {
            "primary_operator_pipeline_entrypoint": {
                "airflow_dag_id": "audience_engine_operator_main"
            }
        },
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_recent_run_events",
        lambda limit=20: [],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_jobs",
        lambda limit=20: [],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_attempts",
        lambda limit=50, run_id=None: [],
    )
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "list_lifecycle_audit",
        lambda limit=20: [],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [
            {
                "version_id": VERSION_ID,
                "entity_key": "fs_credit",
                "version": "fs_credit_v1",
                "lifecycle_state": "active",
                "payload": {"owner": "risk-team"},
            }
        ],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: {
            "version_id": VERSION_ID,
            "entity_key": "fs_credit",
            "version": "fs_credit_v1",
            "lifecycle_state": "active",
            "payload": {"owner": "risk-team"},
        },
    )
    monkeypatch.setattr(
        control_plane_mgmt,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [],
    )


def test_dashboard_renders_role_entry_points_and_journey(monkeypatch: pytest.MonkeyPatch):
    _patch_operator_dependencies(monkeypatch)
    _login()

    response = client.get("/operator/dashboard")

    assert response.status_code == 200
    assert "Role Entry Points" in response.text
    assert "Campaign User" in response.text
    assert "Data Engineer" in response.text
    assert "ML Analyst" in response.text
    assert "Admin/Operator" in response.text
    assert "Journey: Start Here" in response.text
    assert "docs/UAT_ROLE_FLOWS.md" in response.text
    assert "docs/UAT_SCENARIOS.md" in response.text


@pytest.mark.parametrize(
    ("path", "journey_title"),
    [
        ("/operator/defaults", "Journey: Inspect Defaults"),
        ("/operator/trigger-run", "Journey: Trigger a Run"),
        ("/operator/recent-runs", "Journey: Review Recent Runs"),
        ("/operator/delivery", "Journey: Review Delivery"),
        ("/operator/explain-audit", "Journey: Explain and Audit"),
        ("/operator/readiness", "Journey: Check Readiness"),
        (
            "/operator/control-plane/versions?entity_type=feature_sets&entity_key=fs_credit",
            "Journey: Inspect Versions and Governance",
        ),
    ],
)
def test_key_pages_render_expected_journey_guidance(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    journey_title: str,
):
    _patch_operator_dependencies(monkeypatch)
    _login()

    response = client.get(path)

    assert response.status_code == 200
    assert journey_title in response.text
    assert "You are here" in response.text


def test_control_plane_journey_mentions_governance_blockers(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_operator_dependencies(monkeypatch)
    _login()

    response = client.get(
        "/operator/control-plane/versions?entity_type=feature_sets&entity_key=fs_credit"
    )

    assert response.status_code == 200
    assert "inspect promotion readiness checks, blockers, and non-blocking gaps" in response.text
