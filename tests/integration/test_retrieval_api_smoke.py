import pytest
from fastapi.testclient import TestClient

from services.retrieval_api import app as app_module

client = TestClient(app_module.app)

CAMPAIGN_KEY = "campaign-test-key"
ADMIN_KEY = "admin-test-key"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("AE_CAMPAIGN_API_KEYS", CAMPAIGN_KEY)
    monkeypatch.setenv("AE_ADMIN_API_KEYS", ADMIN_KEY)


def _headers(key: str) -> dict[str, str]:
    return {"X-AE-API-Key": key}


def test_healthz_smoke():
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version_bundle"] is None or isinstance(body["version_bundle"], dict)


def test_metrics_endpoint_does_not_redirect():
    bare = client.get("/metrics", follow_redirects=False)
    slash = client.get("/metrics/", follow_redirects=False)
    assert bare.status_code == 200
    assert slash.status_code == 200
    assert bare.headers.get("location") is None
    assert "python_info" in bare.text or "# HELP" in bare.text


def test_retrieve_requires_query():
    response = client.post(
        "/v1/retrieve",
        json={"top_k": 5},
        headers=_headers(CAMPAIGN_KEY),
    )
    assert response.status_code == 400
    assert "Provide query_text or query_customer_id" in response.text


def test_retrieve_smoke_with_monkeypatched_backend(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "retrieve_similar",
        lambda **kwargs: [{"customer_id": "cust_00001", "score": 0.99, "payload": {}}],
    )
    response = client.post(
        "/v1/retrieve",
        json={"top_k": 1, "query_text": "test"},
        headers=_headers(CAMPAIGN_KEY),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["customer_id"] == "cust_00001"


def test_retrieve_requires_api_key():
    response = client.post("/v1/retrieve", json={"top_k": 1, "query_text": "test"})
    assert response.status_code == 401
    assert "Missing API key header" in response.text


def test_protected_endpoint_fails_closed_when_rbac_not_configured(monkeypatch):
    monkeypatch.delenv("AE_CAMPAIGN_API_KEYS", raising=False)
    monkeypatch.delenv("AE_ADMIN_API_KEYS", raising=False)
    response = client.post(
        "/v1/retrieve",
        json={"top_k": 1, "query_text": "test"},
        headers=_headers(CAMPAIGN_KEY),
    )
    assert response.status_code == 403
    assert "RBAC is not configured" in response.text


def test_get_policy_decision_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "fetch_policy_decision_audit",
        lambda run_id, customer_id: {
            "run_id": run_id,
            "campaign_id": "camp_x",
            "customer_id": customer_id,
            "decision": "reject",
            "reason_codes": ["SUPPRESS_DNC"],
            "policy_version": "policy_credit_v1",
            "fs_version": "fs_credit_v1",
            "emb_version": "fs_credit_v1+prompt_credit_v1+nomic-embed-text",
            "model_version": "nomic-embed-text",
            "index_alias": "audience-serving",
            "index_generation": "customers_fs_credit_v1_8d_20260408030303",
            "decision_ts": "2026-04-08T03:03:03+00:00",
            "explanation": {"evaluation_mode": "rules"},
        },
    )
    response = client.get(
        "/v1/policy/decisions/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/cust-999",
        headers=_headers(ADMIN_KEY),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "e0f62885-0dbc-4d53-b1d5-59fd0be558e2"
    assert body["customer_id"] == "cust-999"
    assert body["decision"] == "reject"
    assert body["reason_codes"] == ["SUPPRESS_DNC"]


def test_get_policy_decision_not_found(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "fetch_policy_decision_audit",
        lambda run_id, customer_id: None,
    )
    response = client.get(
        "/v1/policy/decisions/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/cust-missing",
        headers=_headers(ADMIN_KEY),
    )
    assert response.status_code == 404
    assert "Policy decision not found" in response.text


def test_get_policy_decision_invalid_run_id_returns_422(monkeypatch):
    fetch_called = {"value": False}

    def _unexpected_fetch(run_id, customer_id):
        fetch_called["value"] = True
        return None

    monkeypatch.setattr(app_module, "fetch_policy_decision_audit", _unexpected_fetch)
    response = client.get(
        "/v1/policy/decisions/not-a-uuid/cust-any",
        headers=_headers(ADMIN_KEY),
    )
    assert response.status_code == 422
    assert "Invalid run_id format" in response.text
    assert fetch_called["value"] is False


def test_campaign_role_cannot_access_admin_policy_decision(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "fetch_policy_decision_audit",
        lambda run_id, customer_id: {"run_id": run_id, "customer_id": customer_id},
    )
    response = client.get(
        "/v1/policy/decisions/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/cust-001",
        headers=_headers(CAMPAIGN_KEY),
    )
    assert response.status_code == 403
    assert "Admin/operator role is required" in response.text


def test_control_plane_model_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.control_plane,
        "describe_operational_model",
        lambda: {
            "primary_operator_pipeline_entrypoint": {
                "airflow_dag_id": "audience_engine_operator_main"
            }
        },
    )
    response = client.get(
        "/v1/admin/control-plane/model",
        headers=_headers(ADMIN_KEY),
    )
    assert response.status_code == 200
    assert (
        response.json()["primary_operator_pipeline_entrypoint"]["airflow_dag_id"]
        == "audience_engine_operator_main"
    )


def test_control_plane_defaults_get_update_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.control_plane,
        "load_operator_defaults",
        lambda: app_module.control_plane.OperatorDefaults(
            default_policy_version="policy_credit_v1",
            default_integration_profile_id="local_snapshot_local_export",
            default_delivery_target_id="crm_postgres_outbox",
        ),
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "save_operator_defaults",
        lambda default_policy_version=None,
        default_integration_profile_id=None,
        default_delivery_target_id=None: app_module.control_plane.OperatorDefaults(
            default_policy_version=default_policy_version or "policy_credit_v1",
            default_integration_profile_id=default_integration_profile_id
            or "local_snapshot_local_export",
            default_delivery_target_id=default_delivery_target_id
            or "crm_postgres_outbox",
        ),
    )
    get_resp = client.get(
        "/v1/admin/control-plane/defaults",
        headers=_headers(ADMIN_KEY),
    )
    put_resp = client.put(
        "/v1/admin/control-plane/defaults",
        json={
            "default_integration_profile_id": "clickhouse_postgres_export",
            "default_delivery_target_id": "crm_csv_file",
        },
        headers=_headers(ADMIN_KEY),
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["default_policy_version"] == "policy_credit_v1"
    assert get_resp.json()["default_delivery_target_id"] == "crm_postgres_outbox"
    assert put_resp.status_code == 200
    assert (
        put_resp.json()["default_integration_profile_id"]
        == "clickhouse_postgres_export"
    )
    assert put_resp.json()["default_delivery_target_id"] == "crm_csv_file"


def test_control_plane_defaults_rejects_planned_profile(monkeypatch):
    def _raise(
        *,
        default_policy_version=None,
        default_integration_profile_id=None,
        default_delivery_target_id=None,
    ):
        raise ValueError(
            "Default integration profile is not implemented: "
            "salesforce_future_profile (status=planned)"
        )

    monkeypatch.setattr(
        app_module.control_plane,
        "save_operator_defaults",
        _raise,
    )
    response = client.put(
        "/v1/admin/control-plane/defaults",
        json={"default_integration_profile_id": "salesforce_future_profile"},
        headers=_headers(ADMIN_KEY),
    )
    assert response.status_code == 400
    assert "Default integration profile is not implemented" in response.text


def test_control_plane_integrations_policies_and_runs_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.control_plane,
        "list_source_connectors",
        lambda include_planned=True: [{"source_id": "snapshot_jsonl"}],
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_export_targets",
        lambda include_planned=True: [{"export_id": "local_jsonl"}],
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "list_integration_profiles",
        lambda include_planned=True: [{"profile_id": "local_snapshot_local_export"}],
    )
    monkeypatch.setattr(
        app_module.integrations,
        "annotate_runtime_readiness",
        lambda sources, exports, profiles: {
            "sources": [{"source_id": "snapshot_jsonl", "runtime_runnable": True}],
            "exports": [{"export_id": "local_jsonl", "runtime_runnable": True}],
            "profiles": [
                {
                    "profile_id": "local_snapshot_local_export",
                    "runtime_runnable": True,
                }
            ],
        },
    )
    monkeypatch.setattr(
        app_module.control_plane,
        "load_operator_defaults",
        lambda: app_module.control_plane.OperatorDefaults(
            default_policy_version="policy_credit_v1",
            default_integration_profile_id="local_snapshot_local_export",
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
        "list_recent_run_events",
        lambda limit=20: [{"run_id": "run-1", "status": "ok"}],
    )
    monkeypatch.setattr(
        app_module,
        "_load_latest_summary",
        lambda: {"status": "ok", "versions": {"run_id": "run-1"}},
    )
    integrations_resp = client.get(
        "/v1/admin/control-plane/integrations",
        headers=_headers(ADMIN_KEY),
    )
    policies_resp = client.get(
        "/v1/admin/control-plane/policies",
        headers=_headers(ADMIN_KEY),
    )
    runs_resp = client.get(
        "/v1/admin/runs/recent?limit=10",
        headers=_headers(ADMIN_KEY),
    )
    summary_resp = client.get(
        "/v1/admin/runs/latest-summary",
        headers=_headers(ADMIN_KEY),
    )
    assert integrations_resp.status_code == 200
    assert integrations_resp.json()["sources"][0]["source_id"] == "snapshot_jsonl"
    assert integrations_resp.json()["profiles"][0]["runtime_runnable"] is True
    assert policies_resp.status_code == 200
    assert policies_resp.json()["default_policy_version"] == "policy_credit_v1"
    assert runs_resp.status_code == 200
    assert runs_resp.json()["count"] == 1
    assert summary_resp.status_code == 200
    assert summary_resp.json()["versions"]["run_id"] == "run-1"


def test_trigger_operator_run_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.run_flow,
        "run_minimal_vertical_slice",
        lambda campaign_id=None,
        policy_version=None,
        integration_profile_id=None,
        delivery_target_id=None,
        feature_set_version_id=None,
        model_version_id=None,
        embedding_model_version_id=None,
        policy_version_id=None,
        audience_definition_version_id=None,
        requested_size=20: {
            "status": "ok",
            "versions": {
                "run_id": "e0f62885-0dbc-4d53-b1d5-59fd0be558e2",
                "campaign_id": campaign_id or "camp_default",
                "policy_version": policy_version or "policy_credit_v1",
            },
            "operations": {
                "integration_profile_id": integration_profile_id
                or "local_snapshot_local_export",
                "export_profile_id": integration_profile_id
                or "local_snapshot_local_export",
                "delivery_target_id": delivery_target_id or "crm_postgres_outbox",
            },
        },
    )
    response = client.post(
        "/v1/admin/runs/trigger",
        json={
            "campaign_id": "camp_manual",
            "policy_version": "policy_credit_v1",
            "integration_profile_id": "local_snapshot_local_export",
            "delivery_target_id": "crm_postgres_outbox",
            "requested_size": 25,
        },
        headers=_headers(ADMIN_KEY),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["campaign_id"] == "camp_manual"
    assert body["integration_profile_id"] == "local_snapshot_local_export"
    assert body["export_profile_id"] == "local_snapshot_local_export"
    assert body["delivery_target_id"] == "crm_postgres_outbox"


def test_control_plane_registry_endpoints_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "create_draft_version",
        lambda **kwargs: {
            "version_id": "ad7f34f3-54d3-4caf-b603-ff3f064adb3d",
            "entity_key": kwargs["entity_key"],
            "version": kwargs["version"],
            "lifecycle_state": "draft",
            "payload": kwargs.get("metadata", {}),
        },
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [
            {
                "version_id": "ad7f34f3-54d3-4caf-b603-ff3f064adb3d",
                "entity_key": "fs_credit",
                "version": "fs_credit_v2",
                "lifecycle_state": "draft",
                "payload": {},
            }
        ],
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "get_active_version",
        lambda **kwargs: {
            "version_id": "c4c5f52d-ec77-4fa8-8963-03de9ad89866",
            "entity_key": "fs_credit",
            "version": "fs_credit_v1",
            "lifecycle_state": "active",
            "payload": {},
        },
    )
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "transition_version_state",
        lambda **kwargs: {
            "version_id": kwargs["version_id"],
            "entity_key": "fs_credit",
            "version": "fs_credit_v2",
            "lifecycle_state": kwargs["target_state"],
            "payload": {},
        },
    )

    create_resp = client.post(
        "/v1/admin/control-plane/registry/feature_sets/versions/draft",
        json={
            "entity_key": "fs_credit",
            "version": "fs_credit_v2",
            "metadata": {"owner": "data_engineering"},
            "references": {},
        },
        headers=_headers(ADMIN_KEY),
    )
    list_resp = client.get(
        "/v1/admin/control-plane/registry/feature_sets/versions?entity_key=fs_credit",
        headers=_headers(ADMIN_KEY),
    )
    active_resp = client.get(
        "/v1/admin/control-plane/registry/feature_sets/versions/active?entity_key=fs_credit",
        headers=_headers(ADMIN_KEY),
    )
    transition_resp = client.post(
        "/v1/admin/control-plane/registry/feature_sets/versions/ad7f34f3-54d3-4caf-b603-ff3f064adb3d/state",
        json={"target_state": "validated"},
        headers=_headers(ADMIN_KEY),
    )

    assert create_resp.status_code == 200
    assert create_resp.json()["lifecycle_state"] == "draft"
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] == 1
    assert active_resp.status_code == 200
    assert active_resp.json()["lifecycle_state"] == "active"
    assert transition_resp.status_code == 200
    assert transition_resp.json()["lifecycle_state"] == "validated"


def test_trigger_operator_run_passes_explicit_lineage_ids(monkeypatch):
    captured: dict[str, object] = {}

    def _run(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ok",
            "versions": {
                "run_id": "e0f62885-0dbc-4d53-b1d5-59fd0be558e2",
                "campaign_id": "camp_lineage",
                "policy_version": "policy_credit_v1",
            },
            "operations": {
                "integration_profile_id": kwargs.get("integration_profile_id"),
                "export_profile_id": kwargs.get("integration_profile_id"),
                "delivery_target_id": kwargs.get("delivery_target_id"),
            },
        }

    monkeypatch.setattr(app_module.run_flow, "run_minimal_vertical_slice", _run)

    response = client.post(
        "/v1/admin/runs/trigger",
        json={
            "campaign_id": "camp_lineage",
            "policy_version": "policy_credit_v1",
            "export_profile_id": "clickhouse_postgres_export",
            "delivery_target_id": "crm_csv_file",
            "feature_set_version_id": "d4295d8f-c391-4730-b827-5e92f74fdc27",
            "model_version_id": "7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79",
            "embedding_model_version_id": "78de4658-4c27-4835-b29d-f19687093f1d",
            "policy_version_id": "7f3029bd-0eb9-4d81-a0f3-88202523fca6",
            "audience_definition_version_id": "8ac37deb-4e2d-45d7-bbe4-1846a9027dc1",
        },
        headers=_headers(ADMIN_KEY),
    )

    assert response.status_code == 200
    assert captured["integration_profile_id"] == "clickhouse_postgres_export"
    assert captured["feature_set_version_id"] == "d4295d8f-c391-4730-b827-5e92f74fdc27"
    assert captured["model_version_id"] == "7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79"
    assert (
        captured["embedding_model_version_id"]
        == "78de4658-4c27-4835-b29d-f19687093f1d"
    )
    assert captured["policy_version_id"] == "7f3029bd-0eb9-4d81-a0f3-88202523fca6"
    assert (
        captured["audience_definition_version_id"]
        == "8ac37deb-4e2d-45d7-bbe4-1846a9027dc1"
    )


def test_delivery_endpoints_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.control_plane,
        "load_operator_defaults",
        lambda: app_module.control_plane.OperatorDefaults(
            default_policy_version="policy_credit_v1",
            default_integration_profile_id="local_snapshot_local_export",
            default_delivery_target_id="crm_postgres_outbox",
        ),
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_delivery_targets",
        lambda include_planned=True: [
            {
                "delivery_target_id": "crm_postgres_outbox",
                "implementation_status": "implemented",
                "runtime_runnable": True,
            }
        ],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "execute_delivery_for_run",
        lambda **kwargs: {
            "delivery_job_id": "d174ba29-cd17-4ebe-a8fb-7fcba84e7381",
            "run_id": kwargs["run_id"],
            "delivery_target_id": kwargs["delivery_target_id"],
            "status": "delivered",
        },
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_jobs",
        lambda limit=20: [{"delivery_job_id": "job-1", "status": "delivered"}],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_recent_delivery_attempts",
        lambda limit=50, run_id=None: [{"attempt_status": "delivered"}],
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "latest_delivery_summary_for_run",
        lambda run_id: {"run_id": run_id, "status": "delivered"},
    )
    monkeypatch.setattr(
        app_module.delivery_runner,
        "list_delivery_records_for_run",
        lambda run_id, limit=200: [{"run_id": run_id, "customer_id": "cust_001"}],
    )

    targets_resp = client.get(
        "/v1/admin/control-plane/delivery-targets",
        headers=_headers(ADMIN_KEY),
    )
    trigger_resp = client.post(
        "/v1/admin/delivery/trigger",
        json={"run_id": "e0f62885-0dbc-4d53-b1d5-59fd0be558e2"},
        headers=_headers(ADMIN_KEY),
    )
    jobs_resp = client.get(
        "/v1/admin/delivery/jobs/recent?limit=10",
        headers=_headers(ADMIN_KEY),
    )
    attempts_resp = client.get(
        "/v1/admin/delivery/attempts/recent?limit=10",
        headers=_headers(ADMIN_KEY),
    )
    summary_resp = client.get(
        "/v1/admin/delivery/runs/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/latest-summary",
        headers=_headers(ADMIN_KEY),
    )
    records_resp = client.get(
        "/v1/admin/delivery/runs/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/records?limit=10",
        headers=_headers(ADMIN_KEY),
    )

    assert targets_resp.status_code == 200
    assert targets_resp.json()["default_delivery_target_id"] == "crm_postgres_outbox"
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["status"] == "delivered"
    assert jobs_resp.status_code == 200
    assert jobs_resp.json()["count"] == 1
    assert attempts_resp.status_code == 200
    assert attempts_resp.json()["count"] == 1
    assert summary_resp.status_code == 200
    assert summary_resp.json()["status"] == "delivered"
    assert records_resp.status_code == 200
    assert records_resp.json()["count"] == 1


def test_campaign_role_cannot_update_defaults_or_trigger_run():
    defaults_resp = client.put(
        "/v1/admin/control-plane/defaults",
        json={"default_policy_version": "policy_credit_v1"},
        headers=_headers(CAMPAIGN_KEY),
    )
    trigger_resp = client.post(
        "/v1/admin/runs/trigger",
        json={"campaign_id": "camp_x"},
        headers=_headers(CAMPAIGN_KEY),
    )
    assert defaults_resp.status_code == 403
    assert trigger_resp.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/admin/control-plane/model"),
        ("get", "/v1/admin/control-plane/defaults"),
        ("get", "/v1/admin/control-plane/integrations"),
        ("get", "/v1/admin/control-plane/delivery-targets"),
        ("get", "/v1/admin/control-plane/policies"),
        ("get", "/v1/admin/control-plane/registry/feature_sets/versions"),
        ("get", "/v1/admin/control-plane/registry/feature_sets/versions/active"),
        ("get", "/v1/admin/runs/recent"),
        ("get", "/v1/admin/runs/latest-summary"),
        ("post", "/v1/admin/delivery/trigger"),
        ("get", "/v1/admin/delivery/jobs/recent"),
        ("get", "/v1/admin/delivery/attempts/recent"),
        (
            "get",
            "/v1/admin/delivery/runs/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/latest-summary",
        ),
        ("get", "/v1/admin/delivery/runs/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/records"),
        ("get", "/v1/admin/index/generations/latest"),
        ("get", "/v1/admin/index/generations"),
        ("post", "/v1/admin/index/generations/validate-latest"),
        ("post", "/v1/admin/index/alias/promote-latest"),
        ("post", "/v1/admin/index/alias/rollback-latest"),
        ("get", "/v1/admin/index/lifecycle-audit"),
    ],
)
def test_campaign_role_cannot_access_any_admin_lifecycle_endpoint(method, path):
    response = getattr(client, method)(path, headers=_headers(CAMPAIGN_KEY))
    assert response.status_code == 403
    assert "Admin/operator role is required" in response.text


def test_admin_lifecycle_validate_latest_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "validate_latest",
        lambda actor: {
            "stage": "validate_generation",
            "alias": "audience-serving",
            "collection": "customers_x",
            "checks": {"expected_count": 1, "actual_count": 1},
        },
    )
    response = client.post(
        "/v1/admin/index/generations/validate-latest",
        headers=_headers(ADMIN_KEY),
    )
    assert response.status_code == 200
    assert response.json()["stage"] == "validate_generation"


def test_admin_lifecycle_promote_and_rollback_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "promote_latest",
        lambda actor: {
            "stage": "promote_alias",
            "alias": "audience-serving",
            "collection": "customers_v2",
            "previous_collection": "customers_v1",
        },
    )
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "rollback_latest",
        lambda actor: {
            "stage": "rollback_alias",
            "alias": "audience-serving",
            "collection": "customers_v1",
            "rolled_back_from": "customers_v2",
        },
    )
    promote = client.post(
        "/v1/admin/index/alias/promote-latest",
        headers=_headers(ADMIN_KEY),
    )
    rollback = client.post(
        "/v1/admin/index/alias/rollback-latest",
        headers=_headers(ADMIN_KEY),
    )
    assert promote.status_code == 200
    assert promote.json()["stage"] == "promote_alias"
    assert rollback.status_code == 200
    assert rollback.json()["stage"] == "rollback_alias"


def test_admin_lifecycle_list_endpoints_smoke(monkeypatch):
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "get_generation_status",
        lambda status=None, alias_name=None: {
            "alias_name": alias_name or "audience-serving",
            "collection_name": "customers_v2",
            "status": status or "promoted",
        },
    )
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "list_generations",
        lambda limit=20, status=None, alias_name=None: [
            {
                "alias_name": alias_name or "audience-serving",
                "collection_name": "customers_v2",
                "status": status or "promoted",
            }
        ],
    )
    monkeypatch.setattr(
        app_module.lifecycle_service,
        "list_lifecycle_audit",
        lambda limit=20, alias_name=None: [
            {
                "id": 1,
                "action": "promote_alias",
                "alias_name": alias_name or "audience-serving",
                "actor_role": "system_internal",
                "actor_id": "system:test",
                "outcome": "success",
                "details": {},
                "action_ts": "2026-04-08T00:00:00+00:00",
            }
        ],
    )
    latest = client.get(
        "/v1/admin/index/generations/latest",
        headers=_headers(ADMIN_KEY),
    )
    generations = client.get(
        "/v1/admin/index/generations?limit=10",
        headers=_headers(ADMIN_KEY),
    )
    lifecycle_audit = client.get(
        "/v1/admin/index/lifecycle-audit?limit=10",
        headers=_headers(ADMIN_KEY),
    )
    assert latest.status_code == 200
    assert latest.json()["collection_name"] == "customers_v2"
    assert generations.status_code == 200
    assert generations.json()["count"] == 1
    assert lifecycle_audit.status_code == 200
    assert lifecycle_audit.json()["count"] == 1
