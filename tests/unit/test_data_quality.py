import json

import pytest

from pipelines.minimal_slice.data_quality import (
    DataQualityError,
    validate_embeddings_artifact,
    validate_feature_mart_contract,
    validate_raw_contract,
)


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_validate_raw_contract_passes_for_minimal_required_fields(tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    _write_jsonl(
        raw_path,
        [
            {"customer_id": "cust_1", "event_ts": "2026-04-08T00:00:00+00:00"},
            {"customer_id": "cust_2", "event_ts": "2026-04-08T00:00:01+00:00"},
        ],
    )

    result = validate_raw_contract(raw_path)
    assert result["status"] == "passed"
    assert result["record_count"] == 2


def test_validate_feature_mart_contract_fails_on_missing_required_field(tmp_path):
    feature_mart_path = tmp_path / "feature_mart.jsonl"
    _write_jsonl(
        feature_mart_path,
        [
            {
                "customer_id": "cust_1",
                "fs_version": "fs_credit_v1",
                "policy_version": "policy_credit_v1",
                "customer_age_years": 30,
                "customer_tenure_months": 12,
                "credit_score_band": "high",
                "delinquency_12m_count": 0,
                "utilization_ratio_avg_3m": 0.2,
                "card_spend_total_3m": 1200.0,
                "digital_engagement_score": 0.5,
                "is_employee_flag": False,
            }
        ],
    )

    with pytest.raises(DataQualityError, match="DQ_REQUIRED_FIELD_MISSING"):
        validate_feature_mart_contract(feature_mart_path)


def test_validate_embeddings_artifact_fails_on_mixed_versions(tmp_path):
    embeddings_path = tmp_path / "embeddings.jsonl"
    _write_jsonl(
        embeddings_path,
        [
            {
                "customer_id": "cust_1",
                "fs_version": "fs_credit_v1",
                "emb_version": "emb_v1",
                "policy_version": "policy_credit_v1",
                "vector": [0.1, 0.2],
            },
            {
                "customer_id": "cust_2",
                "fs_version": "fs_credit_v1",
                "emb_version": "emb_v2",
                "policy_version": "policy_credit_v1",
                "vector": [0.3, 0.4],
            },
        ],
    )

    with pytest.raises(DataQualityError, match="DQ_EMBEDDING_VERSION_MIXED"):
        validate_embeddings_artifact(embeddings_path=embeddings_path)
