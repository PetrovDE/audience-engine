from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.retrieval_api import app as app_module

client = TestClient(app_module.app)

CAMPAIGN_KEY = "campaign-test-key"
ADMIN_KEY = "admin-test-key"
OPERATOR_UI_USERNAME = "admin"
OPERATOR_UI_PASSWORD = "203217"
RUN_ID = "e0f62885-0dbc-4d53-b1d5-59fd0be558e2"
VERSION_ID = "ad7f34f3-54d3-4caf-b603-ff3f064adb3d"


def apply_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE_CAMPAIGN_API_KEYS", CAMPAIGN_KEY)
    monkeypatch.setenv("AE_ADMIN_API_KEYS", ADMIN_KEY)
    monkeypatch.setenv("OPERATOR_UI_USERNAME", OPERATOR_UI_USERNAME)
    monkeypatch.setenv("OPERATOR_UI_PASSWORD", OPERATOR_UI_PASSWORD)
    client.cookies.clear()


def login(next_path: str = "/operator/dashboard") -> None:
    response = client.post(
        "/operator/login",
        data={
            "username": OPERATOR_UI_USERNAME,
            "password": OPERATOR_UI_PASSWORD,
            "next": next_path,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def patch_common_operator_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
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
