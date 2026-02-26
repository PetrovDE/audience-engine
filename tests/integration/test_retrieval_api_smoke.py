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
