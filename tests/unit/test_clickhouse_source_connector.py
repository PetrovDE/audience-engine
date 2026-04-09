from __future__ import annotations

import json

import pytest

from pipelines.minimal_slice import feature_mart, storage


def test_read_feature_slice_from_clickhouse_executes_query_with_limit(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeResult:
        column_names = ["customer_id", "customer_tenure_months"]
        result_rows = [("cust_1", 12)]

    class _FakeClient:
        def query(self, query: str):
            captured["query"] = query
            return _FakeResult()

    class _FakeModule:
        @staticmethod
        def get_client(**kwargs):
            captured["client_kwargs"] = kwargs
            return _FakeClient()

    monkeypatch.setattr(storage, "_safe_import_clickhouse", lambda: _FakeModule())
    monkeypatch.setattr(storage.config, "CLICKHOUSE_HOST", "clickhouse.local")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_PORT", 8123)
    monkeypatch.setattr(storage.config, "CLICKHOUSE_DB", "audience_engine")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_USER", "audience_engine")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_PASSWORD", "secret")
    monkeypatch.setattr(
        storage.config,
        "CLICKHOUSE_FEATURE_SLICE_QUERY",
        "SELECT customer_id, customer_tenure_months FROM feature_mart_snapshot",
    )
    monkeypatch.setattr(storage.config, "CLICKHOUSE_FEATURE_SLICE_LIMIT", 25)

    rows = storage.read_feature_slice_from_clickhouse()

    assert rows == [{"customer_id": "cust_1", "customer_tenure_months": 12}]
    assert captured["client_kwargs"] == {
        "host": "clickhouse.local",
        "port": 8123,
        "username": "audience_engine",
        "password": "secret",
        "database": "audience_engine",
    }
    assert "LIMIT 25" in str(captured["query"])


def test_clickhouse_feature_mart_requires_contract_columns(monkeypatch, tmp_path):
    fs_payload = {
        "fs_version": "fs_credit_v1",
        "features": [
            "customer_age_years",
            "customer_tenure_months",
            "credit_score_band",
            "delinquency_12m_count",
            "utilization_ratio_avg_3m",
            "card_spend_total_3m",
            "digital_engagement_score",
        ],
    }
    fs_path = tmp_path / "fs.yaml"
    fs_path.write_text(json.dumps(fs_payload), encoding="utf-8")
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text('{"customer_id":"cust_1"}\n', encoding="utf-8")

    monkeypatch.setattr(feature_mart, "FEATURE_SET_PATH", fs_path)
    monkeypatch.setattr(feature_mart, "validate_clickhouse_source_config", lambda: [])
    monkeypatch.setattr(
        feature_mart,
        "read_feature_slice_from_clickhouse",
        lambda: [
            {
                "customer_id": "cust_1",
                "customer_age_years": 35,
                "customer_tenure_months": 24,
                "credit_score_band": "A",
                "delinquency_12m_count": 0,
                "utilization_ratio_avg_3m": 0.21,
                "card_spend_total_3m": 1200.0,
                "digital_engagement_score": 0.8,
                "is_employee_flag": 0,
                "do_not_contact_flag": 0,
                "opt_out_flag": 0,
                "legal_suppression_flag": 0,
                "segment_id": "mass",
                "product_line": "credit_card",
            }
        ],
    )

    with pytest.raises(ValueError, match="missing required columns"):
        feature_mart.build_feature_mart_snapshot(
            raw_path=raw_path,
            output_path=tmp_path / "feature_mart.jsonl",
            source_mode="clickhouse",
        )


def test_probe_clickhouse_source_connectivity_executes_select_1(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeClient:
        def query(self, query: str):
            captured["probe_query"] = query
            return object()

    class _FakeModule:
        @staticmethod
        def get_client(**kwargs):
            captured["client_kwargs"] = kwargs
            return _FakeClient()

    monkeypatch.setattr(storage, "_safe_import_clickhouse", lambda: _FakeModule())
    monkeypatch.setattr(storage.config, "CLICKHOUSE_HOST", "clickhouse.local")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_PORT", 8123)
    monkeypatch.setattr(storage.config, "CLICKHOUSE_DB", "audience_engine")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_USER", "audience_engine")
    monkeypatch.setattr(storage.config, "CLICKHOUSE_PASSWORD", "secret")
    monkeypatch.setattr(
        storage.config,
        "CLICKHOUSE_FEATURE_SLICE_QUERY",
        "SELECT customer_id FROM feature_mart_snapshot",
    )
    monkeypatch.setattr(
        storage.config, "INTEGRATION_READINESS_PROBE_TIMEOUT_SECONDS", 1.5
    )

    storage.probe_clickhouse_source_connectivity()

    assert captured["probe_query"] == "SELECT 1"
    assert captured["client_kwargs"]["host"] == "clickhouse.local"
    assert captured["client_kwargs"]["connect_timeout"] == 1.5
