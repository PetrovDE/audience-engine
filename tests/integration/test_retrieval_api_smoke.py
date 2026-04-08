from fastapi.testclient import TestClient

from services.retrieval_api import app as app_module

client = TestClient(app_module.app)


def test_healthz_smoke():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version_bundle": None}


def test_retrieve_requires_query():
    response = client.post("/v1/retrieve", json={"top_k": 5})
    assert response.status_code == 400
    assert "Provide query_text or query_customer_id" in response.text


def test_retrieve_smoke_with_monkeypatched_backend(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "retrieve_similar",
        lambda **kwargs: [
            {"customer_id": "cust_00001", "score": 0.99, "payload": {}}
        ],
    )
    response = client.post("/v1/retrieve", json={"top_k": 1, "query_text": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["customer_id"] == "cust_00001"


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
        "/v1/policy/decisions/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/cust-999"
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
        "/v1/policy/decisions/e0f62885-0dbc-4d53-b1d5-59fd0be558e2/cust-missing"
    )
    assert response.status_code == 404
    assert "Policy decision not found" in response.text


def test_get_policy_decision_invalid_run_id_returns_422(monkeypatch):
    fetch_called = {"value": False}

    def _unexpected_fetch(run_id, customer_id):
        fetch_called["value"] = True
        return None

    monkeypatch.setattr(app_module, "fetch_policy_decision_audit", _unexpected_fetch)
    response = client.get("/v1/policy/decisions/not-a-uuid/cust-any")
    assert response.status_code == 422
    assert "Invalid run_id format" in response.text
    assert fetch_called["value"] is False
