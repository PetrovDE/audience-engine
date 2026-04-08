from __future__ import annotations

import json

import pytest

pytest.importorskip("psycopg")

from pipelines.minimal_slice import run_flow
from pipelines.minimal_slice.data_quality import DataQualityError
from pipelines.version_bundle import VersionBundle


def test_run_flow_fails_when_runtime_embedding_lineage_mismatches_bundle(
    monkeypatch, tmp_path
):
    bundle = VersionBundle(
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
        index_alias="audience-serving",
        concrete_qdrant_collection="audience-serving-fs_credit_v1-deadbeef",
        run_id="e0f62885-0dbc-4d53-b1d5-59fd0be558e2",
        campaign_id="camp_test",
    )
    feature_mart_path = tmp_path / "feature_mart.jsonl"
    feature_mart_path.write_text("", encoding="utf-8")
    embeddings_path = tmp_path / "embeddings.jsonl"
    embeddings_path.write_text("", encoding="utf-8")
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(
        '{"customer_id":"cust_00001","event_ts":"2026-04-08T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_flow, "_build_and_validate_bundle", lambda campaign_id: bundle
    )
    monkeypatch.setattr(
        run_flow,
        "generate_synthetic_data",
        lambda customer_count, seed: {
            "raw": raw_path,
            "blacklist": tmp_path / "blacklist.txt",
            "comm_history": tmp_path / "comm_history.jsonl",
        },
    )
    monkeypatch.setattr(
        run_flow, "validate_raw_contract", lambda raw_path: {"status": "passed"}
    )
    monkeypatch.setattr(
        run_flow,
        "validate_feature_mart_contract",
        lambda feature_mart_path: {"status": "passed"},
    )
    monkeypatch.setattr(
        run_flow,
        "validate_embeddings_artifact",
        lambda embeddings_path, expected_emb_version=None: {"status": "passed"},
    )
    monkeypatch.setattr(
        run_flow,
        "build_feature_mart_snapshot",
        lambda raw_path, output_path, source_mode, run_id: feature_mart_path,
    )
    monkeypatch.setattr(
        run_flow,
        "build_embeddings",
        lambda feature_mart_path, ollama_model: (embeddings_path, 8),
    )
    monkeypatch.setattr(
        run_flow,
        "read_embeddings_emb_version",
        lambda path: "fs_credit_v1+prompt_credit_v1+other-model-v2",
    )

    with pytest.raises(ValueError, match="Embedding lineage mismatch at runtime"):
        run_flow.run_minimal_vertical_slice(campaign_id="camp_test")


def test_run_flow_fails_early_on_raw_data_quality_violation(monkeypatch, tmp_path):
    bundle = VersionBundle(
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
        index_alias="audience-serving",
        concrete_qdrant_collection="audience-serving-fs_credit_v1-deadbeef",
        run_id="e0f62885-0dbc-4d53-b1d5-59fd0be558e2",
        campaign_id="camp_test",
    )
    bad_raw_path = tmp_path / "raw_bad.jsonl"
    bad_raw_path.write_text('{"customer_id":"cust_00001"}\n', encoding="utf-8")
    summary_path = tmp_path / "run_summary.json"

    feature_mart_called = {"value": False}

    def _unexpected_feature_mart(*args, **kwargs):
        feature_mart_called["value"] = True
        raise AssertionError(
            "feature mart stage should not execute on raw quality failure"
        )

    monkeypatch.setattr(
        run_flow, "_build_and_validate_bundle", lambda campaign_id: bundle
    )
    monkeypatch.setattr(
        run_flow,
        "generate_synthetic_data",
        lambda customer_count, seed: {
            "raw": bad_raw_path,
            "blacklist": tmp_path / "blacklist.txt",
            "comm_history": tmp_path / "comm_history.jsonl",
        },
    )
    monkeypatch.setattr(
        run_flow, "build_feature_mart_snapshot", _unexpected_feature_mart
    )
    monkeypatch.setattr(run_flow, "SUMMARY_PATH", summary_path)

    with pytest.raises(DataQualityError, match="DQ_REQUIRED_FIELD_MISSING"):
        run_flow.run_minimal_vertical_slice(campaign_id="camp_test")

    assert feature_mart_called["value"] is False
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["quality"]["error"]["code"] == "DQ_REQUIRED_FIELD_MISSING"


def test_run_flow_uses_audited_lifecycle_service_path(monkeypatch, tmp_path):
    bundle = VersionBundle(
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
        index_alias="audience-serving",
        concrete_qdrant_collection="audience-serving-fs_credit_v1-deadbeef",
        run_id="e0f62885-0dbc-4d53-b1d5-59fd0be558e2",
        campaign_id="camp_test",
    )
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(
        '{"customer_id":"cust_00001","event_ts":"2026-04-08T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    feature_mart_path = tmp_path / "feature_mart.jsonl"
    feature_mart_path.write_text("{}", encoding="utf-8")
    embeddings_path = tmp_path / "embeddings.jsonl"
    embeddings_path.write_text("{}", encoding="utf-8")

    calls: list[str] = []

    monkeypatch.setattr(
        run_flow, "_build_and_validate_bundle", lambda campaign_id: bundle
    )
    monkeypatch.setattr(
        run_flow,
        "generate_synthetic_data",
        lambda customer_count, seed: {
            "raw": raw_path,
            "blacklist": tmp_path / "blacklist.txt",
            "comm_history": tmp_path / "comm_history.jsonl",
        },
    )
    monkeypatch.setattr(
        run_flow, "validate_raw_contract", lambda raw_path: {"status": "passed"}
    )
    monkeypatch.setattr(
        run_flow,
        "build_feature_mart_snapshot",
        lambda raw_path, output_path, source_mode, run_id: feature_mart_path,
    )
    monkeypatch.setattr(
        run_flow,
        "validate_feature_mart_contract",
        lambda feature_mart_path: {"status": "passed"},
    )
    monkeypatch.setattr(
        run_flow,
        "build_embeddings",
        lambda feature_mart_path, ollama_model: (embeddings_path, 8),
    )
    monkeypatch.setattr(
        run_flow,
        "validate_embeddings_artifact",
        lambda embeddings_path, expected_emb_version=None: {"status": "passed"},
    )
    monkeypatch.setattr(
        run_flow, "read_embeddings_emb_version", lambda path: bundle.emb_version
    )
    def _build_generation(
        embeddings_path,
        vector_size,
        alias_name_override,
        collection_name_override,
    ):
        calls.append("build_generation")
        return {
            "alias": alias_name_override,
            "collection": collection_name_override,
            "points_count": 1,
        }

    monkeypatch.setattr(
        run_flow,
        "build_generation",
        _build_generation,
    )
    def _validate_latest(actor, embeddings_path):
        calls.append("validate_latest")
        assert actor.actor_id == "system:run_flow"
        return {
            "stage": "validate_generation",
            "alias": bundle.index_alias,
            "collection": bundle.concrete_qdrant_collection,
        }

    def _promote_latest(actor):
        calls.append("promote_latest")
        assert actor.actor_id == "system:run_flow"
        return {
            "stage": "promote_alias",
            "alias": bundle.index_alias,
            "collection": bundle.concrete_qdrant_collection,
        }

    monkeypatch.setattr(run_flow.lifecycle_service, "validate_latest", _validate_latest)
    monkeypatch.setattr(run_flow.lifecycle_service, "promote_latest", _promote_latest)
    monkeypatch.setattr(
        run_flow,
        "retrieve_similar",
        lambda **kwargs: [
            {
                "customer_id": "cust_00001",
                "score": 0.9,
                "payload": {
                    "do_not_contact_flag": False,
                    "is_employee_flag": False,
                    "customer_tenure_months": 12,
                    "delinquency_12m_count": 0,
                    "opt_out_flag": False,
                    "legal_suppression_flag": False,
                },
            }
        ],
    )
    monkeypatch.setattr(
        run_flow,
        "evaluate_policy",
        lambda **kwargs: {
            "status": "ok",
            "summary": {"status": "ok", "approved_count": 1, "rejected_count": 0},
            "results": [
                {
                    "customer_id": "cust_00001",
                    "score": 0.9,
                    "selected": True,
                    "decision": "approve",
                    "reasons": [],
                }
            ],
            "selected": [{"customer_id": "cust_00001", "score": 0.9}],
            "rejection_summary": {},
        },
    )
    monkeypatch.setattr(
        run_flow,
        "export_approved",
        lambda policy_result, output_path: output_path,
    )
    monkeypatch.setattr(run_flow, "minio_is_configured", lambda: False)
    monkeypatch.setattr(run_flow, "_write_audit_to_postgres", lambda **kwargs: None)
    monkeypatch.setattr(run_flow, "SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(run_flow, "EXPORT_PATH", tmp_path / "approved_audience.jsonl")

    summary = run_flow.run_minimal_vertical_slice(campaign_id="camp_test")

    assert calls == ["build_generation", "validate_latest", "promote_latest"]
    assert summary["index"]["stage"] == "promote_alias"
