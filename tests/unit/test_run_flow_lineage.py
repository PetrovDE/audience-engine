from __future__ import annotations

import json

import pytest

pytest.importorskip("psycopg")

from pipelines.minimal_slice import control_plane, run_flow
from pipelines.minimal_slice.data_quality import DataQualityError
from pipelines.version_bundle import VersionBundle


def _run_config() -> control_plane.OperationalRunConfig:
    return control_plane.OperationalRunConfig(
        policy_version="policy_credit_v1",
        policy_selection_source="operator_default",
        integration_profile_id="local_snapshot_local_export",
        integration_selection_source="operator_default",
        delivery_target_id="crm_csv_file",
        delivery_selection_source="operator_default",
        source_id="snapshot_jsonl",
        export_id="local_jsonl",
    )


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
        run_flow.control_plane,
        "resolve_run_configuration",
        lambda policy_version,
        integration_profile_id,
        delivery_target_id=None: _run_config(),
    )
    monkeypatch.setattr(
        run_flow,
        "_build_and_validate_bundle",
        lambda campaign_id, policy_version: bundle,
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
        run_flow.integrations,
        "build_feature_mart_for_profile",
        lambda profile_id, raw_path, output_path, run_id: (
            feature_mart_path,
            {
                "profile_id": profile_id,
                "source_id": "snapshot_jsonl",
                "export_id": "local_jsonl",
            },
        ),
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
        run_flow.control_plane,
        "resolve_run_configuration",
        lambda policy_version,
        integration_profile_id,
        delivery_target_id=None: _run_config(),
    )
    monkeypatch.setattr(
        run_flow,
        "_build_and_validate_bundle",
        lambda campaign_id, policy_version: bundle,
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
        run_flow.integrations,
        "build_feature_mart_for_profile",
        _unexpected_feature_mart,
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
        run_flow.control_plane,
        "resolve_run_configuration",
        lambda policy_version,
        integration_profile_id,
        delivery_target_id=None: _run_config(),
    )
    monkeypatch.setattr(
        run_flow,
        "_build_and_validate_bundle",
        lambda campaign_id, policy_version: bundle,
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
        run_flow.integrations,
        "build_feature_mart_for_profile",
        lambda profile_id, raw_path, output_path, run_id: (
            feature_mart_path,
            {
                "profile_id": profile_id,
                "source_id": "snapshot_jsonl",
                "export_id": "local_jsonl",
            },
        ),
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
        run_flow.integrations,
        "export_for_profile",
        lambda **kwargs: {
            "target_id": "local_jsonl",
            "export_path": str(tmp_path / "approved_audience.jsonl"),
            "export_uri": None,
            "status": "written",
            "profile_id": kwargs.get("profile_id"),
            "source_id": "snapshot_jsonl",
            "export_id": "local_jsonl",
            "profile_status": "implemented",
        },
    )
    monkeypatch.setattr(
        run_flow.delivery_runner,
        "execute_delivery_for_run",
        lambda **kwargs: {
            "delivery_job_id": "6c9d9086-140f-4d2c-88f9-845d4e6ad1ee",
            "delivery_target_id": "crm_csv_file",
            "status": "delivered",
            "rows_delivered": 1,
            "rows_skipped_conflict": 0,
            "artifact_uri": str(tmp_path / "crm_delivery_audience.csv"),
        },
    )
    monkeypatch.setattr(run_flow, "_write_audit_to_postgres", lambda **kwargs: None)
    monkeypatch.setattr(run_flow, "SUMMARY_PATH", tmp_path / "summary.json")

    summary = run_flow.run_minimal_vertical_slice(campaign_id="camp_test")

    assert calls == ["build_generation", "validate_latest", "promote_latest"]
    assert summary["index"]["stage"] == "promote_alias"


def test_run_flow_logs_event_on_configuration_resolution_failure(monkeypatch):
    events: list[dict] = []

    def _raise_config_failure(
        policy_version, integration_profile_id, delivery_target_id=None
    ):
        raise ValueError(
            "Selected integration profile is not implemented: "
            "salesforce_future_profile (status=planned)"
        )

    monkeypatch.setattr(
        run_flow.control_plane,
        "resolve_run_configuration",
        _raise_config_failure,
    )
    monkeypatch.setattr(
        run_flow.control_plane,
        "append_run_event",
        lambda event: events.append(event),
    )

    with pytest.raises(ValueError, match="not implemented"):
        run_flow.run_minimal_vertical_slice(
            campaign_id="camp_config_fail",
            policy_version="policy_credit_v1",
            integration_profile_id="salesforce_future_profile",
            delivery_target_id="crm_api_future",
            requested_size=30,
        )

    assert len(events) == 1
    event = events[0]
    assert event["status"] == "failed"
    assert event["error"]["code"] == "RUN_FAILED_PRECHECK"
    assert event["error"]["stage"] == "resolve_run_configuration"
    assert event["campaign_id"] == "camp_config_fail"
    assert event["policy_version"] == "policy_credit_v1"
    assert event["integration_profile_id"] == "salesforce_future_profile"
    assert event["delivery_target_id"] == "crm_api_future"


def test_run_flow_logs_event_on_bundle_preflight_failure(monkeypatch):
    events: list[dict] = []

    monkeypatch.setattr(
        run_flow.control_plane,
        "resolve_run_configuration",
        lambda policy_version,
        integration_profile_id,
        delivery_target_id=None: _run_config(),
    )

    def _raise_bundle_failure(campaign_id, policy_version):
        raise ValueError("policy_version not found in policy registry")

    monkeypatch.setattr(
        run_flow,
        "_build_and_validate_bundle",
        _raise_bundle_failure,
    )
    monkeypatch.setattr(
        run_flow.control_plane,
        "append_run_event",
        lambda event: events.append(event),
    )

    with pytest.raises(ValueError, match="policy_version not found"):
        run_flow.run_minimal_vertical_slice(campaign_id="camp_bundle_fail")

    assert len(events) == 1
    event = events[0]
    assert event["status"] == "failed"
    assert event["error"]["code"] == "RUN_FAILED_PRECHECK"
    assert event["error"]["stage"] == "build_version_bundle_preflight"
    assert event["campaign_id"] == "camp_bundle_fail"
    assert event["policy_version"] == "policy_credit_v1"
    assert event["integration_profile_id"] == "local_snapshot_local_export"
