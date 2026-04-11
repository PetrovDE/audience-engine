from __future__ import annotations

import pytest

from services.retrieval_api import app as app_module
from tests.integration.operator_ui_uat_helpers import (
    RUN_ID,
    apply_auth_env,
    client,
    login,
    patch_common_operator_catalog,
)


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_auth_env(monkeypatch)


def test_uat_pack_dashboard_shows_role_guidance_and_status_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    login()

    response = client.get("/operator/dashboard")

    assert response.status_code == 200
    assert "Role Entry Points" in response.text
    assert "Journey: Start Here" in response.text
    assert "UAT Pack Status (Stage 7)" in response.text
    assert "UAT-1: Campaign User run and outcome review" in response.text
    assert "UAT-5: Provider/model visibility across readiness and registry" in response.text


def test_uat_pack_navigation_discoverability_for_key_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    login()

    response = client.get("/operator/recent-runs")

    assert response.status_code == 200
    assert 'href="/operator/defaults"' in response.text
    assert 'href="/operator/trigger-run"' in response.text
    assert 'href="/operator/recent-runs"' in response.text
    assert 'href="/operator/delivery"' in response.text
    assert 'href="/operator/explain-audit"' in response.text
    assert 'href="/operator/readiness"' in response.text
    assert 'href="/operator/control-plane/versions"' in response.text


def test_uat_pack_happy_path_trigger_run_recent_runs_and_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    monkeypatch.setattr(
        app_module.run_flow,
        "run_minimal_vertical_slice",
        lambda **kwargs: {
            "status": "ok",
            "versions": {"run_id": RUN_ID, "campaign_id": kwargs.get("campaign_id")},
            "operations": {
                "integration_profile_id": "clickhouse_postgres_export",
                "delivery_target_id": "crm_postgres_outbox",
            },
        },
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_recent_run_events",
        lambda limit=20: [
            {
                "event_ts": "2026-04-11T09:00:00+00:00",
                "status": "success",
                "run_id": RUN_ID,
                "campaign_id": "camp_uat_001",
                "policy_version": "policy_credit_v1",
                "integration_profile_id": "clickhouse_postgres_export",
                "delivery_target_id": "crm_postgres_outbox",
                "error": {},
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
                "source_row_count": 20,
                "rows_delivered": 20,
                "rows_skipped_conflict": 0,
            }
        ],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_attempts",
        lambda limit=50, run_id=None: [
            {
                "attempt_ts": "2026-04-11T09:01:00+00:00",
                "run_id": run_id or RUN_ID,
                "delivery_job_id": "job-1",
                "attempt_status": "delivered",
                "details": {"rows": 20},
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
                "delivery_artifact_uri": "outbox://job-1",
            }
        ],
    )

    login()
    trigger = client.post(
        "/operator/trigger-run",
        data={"campaign_id": "camp_uat_001", "requested_size": "20"},
    )
    assert trigger.status_code == 200
    assert f"Run finished. run_id={RUN_ID}" in trigger.text

    recent = client.get("/operator/recent-runs")
    assert recent.status_code == 200
    assert RUN_ID in recent.text
    assert "camp_uat_001" in recent.text

    delivery = client.get(f"/operator/delivery?run_id={RUN_ID}")
    assert delivery.status_code == 200
    assert "job-1" in delivery.text
    assert "outbox://job-1" in delivery.text
