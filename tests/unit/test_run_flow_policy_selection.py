from __future__ import annotations

import pytest

pytest.importorskip("psycopg")

from pipelines.minimal_slice import control_plane, run_flow
from pipelines.version_bundle import VersionBundle


def test_run_flow_binds_selected_policy_version_into_runtime(monkeypatch, tmp_path):
    selected_policy = "policy_credit_v1"
    bundle = VersionBundle(
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        policy_version=selected_policy,
        index_alias="audience-serving",
        concrete_qdrant_collection="audience-serving-fs_credit_v1-abc12345",
        run_id="f6fe6827-a89f-4717-bc38-fb30fdb0d408",
        campaign_id="camp_policy_bind",
    )

    captured: dict[str, str] = {}
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(
        '{"customer_id":"cust_00001","event_ts":"2026-04-08T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    feature_mart_path = tmp_path / "feature_mart.jsonl"
    feature_mart_path.write_text("{}", encoding="utf-8")
    embeddings_path = tmp_path / "embeddings.jsonl"
    embeddings_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        run_flow.control_plane,
        "resolve_run_configuration",
        lambda policy_version,
        integration_profile_id: control_plane.OperationalRunConfig(
            policy_version=selected_policy,
            policy_selection_source="request",
            integration_profile_id="local_snapshot_local_export",
            integration_selection_source="operator_default",
            source_id="snapshot_jsonl",
            export_id="local_jsonl",
        ),
    )

    def _build_bundle(campaign_id, policy_version):
        captured["bundle_policy_version"] = policy_version
        return bundle

    monkeypatch.setattr(run_flow, "_build_and_validate_bundle", _build_bundle)
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
    monkeypatch.setattr(
        run_flow,
        "build_generation",
        lambda **kwargs: {
            "alias": bundle.index_alias,
            "collection": bundle.concrete_qdrant_collection,
        },
    )
    monkeypatch.setattr(
        run_flow.lifecycle_service,
        "validate_latest",
        lambda actor, embeddings_path: {
            "stage": "validate_generation",
            "alias": bundle.index_alias,
            "collection": bundle.concrete_qdrant_collection,
        },
    )
    monkeypatch.setattr(
        run_flow.lifecycle_service,
        "promote_latest",
        lambda actor: {
            "stage": "promote_alias",
            "alias": bundle.index_alias,
            "collection": bundle.concrete_qdrant_collection,
        },
    )
    monkeypatch.setattr(
        run_flow,
        "retrieve_similar",
        lambda **kwargs: [
            {
                "customer_id": "cust_00001",
                "score": 0.5,
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

    def _evaluate_policy(**kwargs):
        captured["policy_gate_policy_version"] = kwargs["policy_version"]
        return {
            "status": "ok",
            "summary": {"status": "ok", "approved_count": 1, "rejected_count": 0},
            "results": [
                {
                    "customer_id": "cust_00001",
                    "score": 0.5,
                    "selected": True,
                    "decision": "approve",
                    "reasons": [],
                }
            ],
            "selected": [{"customer_id": "cust_00001", "score": 0.5}],
            "rejection_summary": {},
        }

    monkeypatch.setattr(run_flow, "evaluate_policy", _evaluate_policy)
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
    monkeypatch.setattr(run_flow, "_write_audit_to_postgres", lambda **kwargs: None)
    monkeypatch.setattr(run_flow, "SUMMARY_PATH", tmp_path / "summary.json")

    summary = run_flow.run_minimal_vertical_slice(
        campaign_id="camp_policy_bind",
        policy_version=selected_policy,
    )

    assert captured["bundle_policy_version"] == selected_policy
    assert captured["policy_gate_policy_version"] == selected_policy
    assert summary["versions"]["policy_version"] == selected_policy
