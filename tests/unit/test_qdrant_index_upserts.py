from pathlib import Path

import pytest

from pipelines.minimal_slice import qdrant_index


class _FakeQdrantClient:
    def __init__(self, fail_plan: list[Exception] | None = None):
        self.fail_plan = fail_plan or []
        self.upsert_batch_sizes: list[int] = []
        self.upsert_attempts = 0
        self.created_collection: str | None = None

    def create_collection(self, collection_name, vectors_config):  # noqa: ANN001
        self.created_collection = collection_name

    def create_payload_index(self, collection_name, field_name, field_schema):  # noqa: ANN001
        return None

    def upsert(self, collection_name, points):  # noqa: ANN001
        self.upsert_attempts += 1
        if self.fail_plan:
            exc = self.fail_plan.pop(0)
            raise exc
        self.upsert_batch_sizes.append(len(points))


def _rows(count: int, *, emb_version: str = "emb_v1") -> list[dict]:
    return [
        {
            "customer_id": f"cust_{i:05d}",
            "emb_version": emb_version,
            "vector": [0.1, 0.2, 0.3],
            "fs_version": "fs_v1",
            "policy_version": "policy_v1",
            "product_line": "credit_card",
            "region_code": "us_west",
            "segment_id": "mass",
            "is_employee_flag": False,
            "do_not_contact_flag": False,
            "opt_out_flag": False,
            "legal_suppression_flag": False,
            "customer_tenure_months": 12,
            "delinquency_12m_count": 0,
        }
        for i in range(count)
    ]


def test_build_generation_batches_by_configured_batch_size(monkeypatch):
    fake_client = _FakeQdrantClient()
    monkeypatch.setattr(qdrant_index, "QdrantClient", lambda url: fake_client)
    monkeypatch.setattr(qdrant_index, "_read_jsonl", lambda path: _rows(5))
    monkeypatch.setattr(qdrant_index, "_record_generation", lambda **kwargs: None)
    monkeypatch.setattr(
        qdrant_index,
        "_create_payload_indexes",
        lambda client, collection_name: None,
    )
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_BATCH_SIZE", 2)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_BACKPRESSURE_SECONDS", 0.0)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_PROGRESS_LOG_EVERY_BATCHES", 1)

    result = qdrant_index.build_generation(
        embeddings_path=Path("ignored.jsonl"),
        vector_size=3,
    )

    assert fake_client.upsert_batch_sizes == [2, 2, 1]
    assert result["upsert"]["batch_size"] == 2
    assert result["upsert"]["batches"] == 3
    assert result["upsert"]["retries"] == 0


def test_build_generation_retries_transient_upsert_failures(monkeypatch):
    fake_client = _FakeQdrantClient(fail_plan=[RuntimeError("503 service unavailable")])
    monkeypatch.setattr(qdrant_index, "QdrantClient", lambda url: fake_client)
    monkeypatch.setattr(qdrant_index, "_read_jsonl", lambda path: _rows(2))
    monkeypatch.setattr(qdrant_index, "_record_generation", lambda **kwargs: None)
    monkeypatch.setattr(
        qdrant_index,
        "_create_payload_indexes",
        lambda client, collection_name: None,
    )
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_BATCH_SIZE", 50)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_BACKOFF_MAX_SECONDS", 0.0)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_BACKOFF_JITTER_SECONDS", 0.0)

    result = qdrant_index.build_generation(
        embeddings_path=Path("ignored.jsonl"),
        vector_size=3,
    )

    assert fake_client.upsert_attempts == 2
    assert result["upsert"]["retries"] == 1


def test_build_generation_does_not_retry_non_transient_failures(monkeypatch):
    fake_client = _FakeQdrantClient(fail_plan=[ValueError("invalid payload schema")])
    monkeypatch.setattr(qdrant_index, "QdrantClient", lambda url: fake_client)
    monkeypatch.setattr(qdrant_index, "_read_jsonl", lambda path: _rows(1))
    monkeypatch.setattr(qdrant_index, "_record_generation", lambda **kwargs: None)
    monkeypatch.setattr(
        qdrant_index,
        "_create_payload_indexes",
        lambda client, collection_name: None,
    )
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_BATCH_SIZE", 10)
    monkeypatch.setattr(qdrant_index, "QDRANT_UPSERT_RETRY_MAX_ATTEMPTS", 3)

    with pytest.raises(ValueError, match="invalid payload schema"):
        qdrant_index.build_generation(
            embeddings_path=Path("ignored.jsonl"),
            vector_size=3,
        )
    assert fake_client.upsert_attempts == 1
