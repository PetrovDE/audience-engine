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


@pytest.mark.parametrize(
    ("method", "path"),
    [
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
