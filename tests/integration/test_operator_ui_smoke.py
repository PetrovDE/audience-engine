import pytest
from fastapi.testclient import TestClient

from services.retrieval_api import app as app_module
from services.retrieval_api import operator_ui as operator_ui_module

client = TestClient(app_module.app)

CAMPAIGN_KEY = "campaign-test-key"
ADMIN_KEY = "admin-test-key"
RUN_ID = "e0f62885-0dbc-4d53-b1d5-59fd0be558e2"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("AE_CAMPAIGN_API_KEYS", CAMPAIGN_KEY)
    monkeypatch.setenv("AE_ADMIN_API_KEYS", ADMIN_KEY)
    client.cookies.clear()


def _login() -> None:
    response = client.post(
        "/operator/login",
        data={"api_key": ADMIN_KEY, "next": "/operator/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _patch_operator_catalog(monkeypatch) -> None:
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
        lambda: [
            {
                "policy_version": "policy_credit_v1",
                "status": "active",
            }
        ],
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


def test_operator_ui_login_and_dashboard_smoke(monkeypatch):
    _patch_operator_catalog(monkeypatch)
    monkeypatch.setattr(
        app_module.control_plane,
        "describe_operational_model",
        lambda: {
            "primary_operator_pipeline_entrypoint": {
                "airflow_dag_id": "audience_engine_operator_main"
            }
        },
    )

    anon = client.get("/operator/dashboard", follow_redirects=False)
    assert anon.status_code == 303
    assert anon.headers["location"].startswith("/operator/login")

    _login()
    response = client.get("/operator/dashboard")
    assert response.status_code == 200
    assert "System Readiness Snapshot" in response.text
    assert "audience_engine_operator_main" in response.text
    assert "policy_credit_v1" in response.text


def test_operator_ui_defaults_submit_calls_control_plane(monkeypatch):
    _patch_operator_catalog(monkeypatch)
    captured: dict[str, str] = {}

    def _save(
        *,
        default_policy_version=None,
        default_integration_profile_id=None,
        default_delivery_target_id=None,
    ):
        captured["default_policy_version"] = default_policy_version
        captured["default_integration_profile_id"] = default_integration_profile_id
        captured["default_delivery_target_id"] = default_delivery_target_id
        return app_module.control_plane.OperatorDefaults(
            default_policy_version=default_policy_version or "policy_credit_v1",
            default_integration_profile_id=default_integration_profile_id
            or "clickhouse_postgres_export",
            default_delivery_target_id=default_delivery_target_id
            or "crm_postgres_outbox",
        )

    monkeypatch.setattr(app_module.control_plane, "save_operator_defaults", _save)

    _login()
    response = client.post(
        "/operator/defaults",
        data={
            "default_policy_version": "policy_credit_v1",
            "default_integration_profile_id": "clickhouse_postgres_export",
            "default_delivery_target_id": "crm_postgres_outbox",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert captured == {
        "default_policy_version": "policy_credit_v1",
        "default_integration_profile_id": "clickhouse_postgres_export",
        "default_delivery_target_id": "crm_postgres_outbox",
    }


def test_operator_ui_trigger_run_calls_run_flow(monkeypatch):
    _patch_operator_catalog(monkeypatch)
    captured: dict[str, object] = {}

    def _run(
        campaign_id=None,
        policy_version=None,
        integration_profile_id=None,
        delivery_target_id=None,
        requested_size=20,
    ):
        captured["campaign_id"] = campaign_id
        captured["policy_version"] = policy_version
        captured["integration_profile_id"] = integration_profile_id
        captured["delivery_target_id"] = delivery_target_id
        captured["requested_size"] = requested_size
        return {
            "status": "ok",
            "versions": {"run_id": RUN_ID, "campaign_id": campaign_id},
            "operations": {
                "integration_profile_id": integration_profile_id
                or "clickhouse_postgres_export",
                "delivery_target_id": delivery_target_id or "crm_postgres_outbox",
            },
        }

    monkeypatch.setattr(app_module.run_flow, "run_minimal_vertical_slice", _run)

    _login()
    response = client.post(
        "/operator/trigger-run",
        data={
            "campaign_id": "camp_ui_001",
            "requested_size": "33",
            "policy_version_override": "policy_credit_v1",
            "integration_profile_id_override": "clickhouse_postgres_export",
            "delivery_target_id_override": "",
        },
    )
    assert response.status_code == 200
    assert captured == {
        "campaign_id": "camp_ui_001",
        "policy_version": "policy_credit_v1",
        "integration_profile_id": "clickhouse_postgres_export",
        "delivery_target_id": None,
        "requested_size": 33,
    }
    assert RUN_ID in response.text


def test_operator_ui_recent_runs_and_delivery_render_returned_structures(monkeypatch):
    _patch_operator_catalog(monkeypatch)
    monkeypatch.setattr(
        app_module.control_plane,
        "list_recent_run_events",
        lambda limit=20: [
            {
                "event_ts": "2026-04-10T12:00:00+00:00",
                "status": "failed",
                "run_id": RUN_ID,
                "campaign_id": "<script>alert(1)</script>",
                "policy_version": "policy_credit_v1",
                "integration_profile_id": "clickhouse_postgres_export",
                "delivery_target_id": "crm_postgres_outbox",
                "error": {"code": "RUN_FAILED_INTERNAL", "detail": "boom"},
            }
        ],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_jobs",
        lambda limit=20: [
            {
                "delivery_job_id": "job-1",
                "run_id": RUN_ID,
                "delivery_target_id": "crm_postgres_outbox",
                "status": "delivered",
                "source_row_count": 12,
                "rows_delivered": 12,
                "rows_skipped_conflict": 0,
            }
        ],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_attempts",
        lambda limit=50, run_id=None: [
            {
                "attempt_ts": "2026-04-10T12:01:00+00:00",
                "run_id": run_id or RUN_ID,
                "delivery_job_id": "job-1",
                "attempt_status": "delivered",
                "details": {"note": "<script>unsafe</script>"},
            }
        ],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "latest_delivery_summary_for_run",
        lambda run_id: {"run_id": run_id, "status": "delivered"},
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_delivery_records_for_run",
        lambda run_id, limit=200: [
            {
                "customer_id": "cust_001",
                "delivery_target_id": "crm_postgres_outbox",
                "delivery_status": "delivered",
                "delivery_artifact_uri": "<script>artifact</script>",
            }
        ],
    )

    _login()
    runs = client.get("/operator/recent-runs")
    assert runs.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in runs.text

    delivery = client.get(f"/operator/delivery?run_id={RUN_ID}")
    assert delivery.status_code == 200
    assert "job-1" in delivery.text
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in delivery.text
    assert "&lt;script&gt;artifact&lt;/script&gt;" in delivery.text


def test_operator_ui_explain_and_audit_page(monkeypatch):
    _patch_operator_catalog(monkeypatch)
    monkeypatch.setattr(
        operator_ui_module,
        "fetch_policy_decision_audit",
        lambda run_id, customer_id: {
            "run_id": run_id,
            "customer_id": customer_id,
            "decision": "reject",
            "reason_codes": ["SUPPRESS_DNC"],
        },
    )
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "list_lifecycle_audit",
        lambda limit=20: [
            {
                "action_ts": "2026-04-10T11:59:00+00:00",
                "action": "promote_alias",
                "alias_name": "audience-serving",
                "outcome": "success",
                "actor_id": "system:airflow",
            }
        ],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_attempts",
        lambda limit=20: [
            {
                "attempt_ts": "2026-04-10T12:01:00+00:00",
                "run_id": RUN_ID,
                "delivery_job_id": "job-99",
                "attempt_status": "delivered",
                "details": {},
            }
        ],
    )

    _login()
    response = client.post(
        "/operator/explain-audit",
        data={"run_id": RUN_ID, "customer_id": "cust_123"},
    )
    assert response.status_code == 200
    assert "SUPPRESS_DNC" in response.text
    assert "promote_alias" in response.text
    assert "job-99" in response.text
