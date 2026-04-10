from __future__ import annotations

import json

import pytest

from pipelines.minimal_slice import control_plane


def test_integration_registry_exposes_implemented_and_planned_connectors():
    sources = control_plane.list_source_connectors(include_planned=True)
    exports = control_plane.list_export_targets(include_planned=True)
    profiles = control_plane.list_integration_profiles(include_planned=True)

    assert any(row["source_id"] == "snapshot_jsonl" for row in sources)
    assert any(row["source_id"] == "crm_salesforce" for row in sources)
    assert any(row["export_id"] == "local_jsonl" for row in exports)
    assert any(row["export_id"] == "postgres_export_table" for row in exports)
    assert any(row["export_id"] == "crm_salesforce_audience" for row in exports)
    assert any(row["profile_id"] == "local_snapshot_local_export" for row in profiles)
    assert any(row["profile_id"] == "clickhouse_postgres_export" for row in profiles)
    assert any(row["profile_id"] == "salesforce_future_profile" for row in profiles)


def test_resolve_run_configuration_uses_defaults_and_request_override(
    monkeypatch, tmp_path
):
    state_path = tmp_path / "operator_state.json"
    monkeypatch.setattr(control_plane, "OPERATOR_STATE_PATH", state_path)

    defaults = control_plane.save_operator_defaults(
        default_policy_version="policy_credit_v1",
        default_integration_profile_id="clickhouse_postgres_export",
        default_delivery_target_id="crm_postgres_outbox",
    )
    assert defaults.default_policy_version == "policy_credit_v1"
    assert defaults.default_delivery_target_id == "crm_postgres_outbox"

    resolved_default = control_plane.resolve_run_configuration(
        policy_version=None,
        integration_profile_id=None,
    )
    assert resolved_default.policy_selection_source == "operator_default"
    assert resolved_default.integration_selection_source == "operator_default"
    assert resolved_default.integration_profile_id == "clickhouse_postgres_export"
    assert resolved_default.delivery_target_id == "crm_postgres_outbox"

    resolved_request = control_plane.resolve_run_configuration(
        policy_version="policy_credit_v1",
        integration_profile_id="clickhouse_postgres_export",
        delivery_target_id="crm_csv_file",
    )
    assert resolved_request.policy_selection_source == "request"
    assert resolved_request.integration_selection_source == "request"
    assert resolved_request.delivery_selection_source == "request"
    assert resolved_request.source_id == "clickhouse_feature_slice"
    assert resolved_request.export_id == "postgres_export_table"
    assert resolved_request.delivery_target_id == "crm_csv_file"


def test_resolve_run_configuration_rejects_planned_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )

    with pytest.raises(ValueError, match="not implemented"):
        control_plane.resolve_run_configuration(
            policy_version="policy_credit_v1",
            integration_profile_id="salesforce_future_profile",
        )


def test_resolve_run_configuration_rejects_planned_delivery_target(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )

    with pytest.raises(ValueError, match="Selected delivery target is not implemented"):
        control_plane.resolve_run_configuration(
            policy_version="policy_credit_v1",
            integration_profile_id="clickhouse_postgres_export",
            delivery_target_id="acrm_api_future",
        )


def test_resolve_run_configuration_rejects_incompatible_profile_delivery_combo(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )
    with pytest.raises(ValueError, match="requires staged export rows"):
        control_plane.resolve_run_configuration(
            policy_version="policy_credit_v1",
            integration_profile_id="local_snapshot_local_export",
            delivery_target_id="crm_csv_file",
        )


def test_load_operator_defaults_falls_back_from_planned_profile(monkeypatch, tmp_path):
    state_path = tmp_path / "operator_state.json"
    monkeypatch.setattr(control_plane, "OPERATOR_STATE_PATH", state_path)
    state_path.write_text(
        json.dumps(
            {
                "default_policy_version": "policy_credit_v1",
                "default_integration_profile_id": "salesforce_future_profile",
                "default_delivery_target_id": "crm_api_future",
            }
        ),
        encoding="utf-8",
    )

    defaults = control_plane.load_operator_defaults()
    assert defaults.default_policy_version == "policy_credit_v1"
    assert defaults.default_integration_profile_id == "clickhouse_postgres_export"
    assert defaults.default_delivery_target_id == "crm_csv_file"


def test_save_operator_defaults_rejects_unknown_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )

    with pytest.raises(ValueError, match="Unknown policy_version"):
        control_plane.save_operator_defaults(default_policy_version="policy_missing_v1")


def test_save_operator_defaults_rejects_planned_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )

    with pytest.raises(
        ValueError, match="Default integration profile is not implemented"
    ):
        control_plane.save_operator_defaults(
            default_integration_profile_id="salesforce_future_profile"
        )


def test_save_operator_defaults_rejects_planned_delivery_target(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )

    with pytest.raises(ValueError, match="Default delivery target is not implemented"):
        control_plane.save_operator_defaults(default_delivery_target_id="crm_api_future")


def test_save_operator_defaults_rejects_incompatible_profile_delivery_combo(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )
    with pytest.raises(ValueError, match="requires staged export rows"):
        control_plane.save_operator_defaults(
            default_integration_profile_id="local_snapshot_local_export",
            default_delivery_target_id="crm_postgres_outbox",
        )


def test_operational_model_declares_distinct_orchestrators():
    model = control_plane.describe_operational_model()
    orchestration = model["orchestration_model"]
    assert "separate orchestrators" in orchestration["summary"]
    assert "run_minimal_vertical_slice" in orchestration["api_orchestrator"]
    assert "audience_engine_dags" in orchestration["airflow_orchestrator"]


def test_run_event_log_roundtrip(monkeypatch, tmp_path):
    events_path = tmp_path / "run_events.jsonl"
    monkeypatch.setattr(control_plane, "RUN_EVENTS_PATH", events_path)

    event = {
        "event_ts": "2026-04-08T00:00:00+00:00",
        "run_id": "run-1",
        "status": "ok",
    }
    control_plane.append_run_event(event)

    rows = control_plane.list_recent_run_events(limit=10)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-1"

    # Ensure file is jsonl-compatible for external tooling.
    raw = events_path.read_text(encoding="utf-8").strip()
    assert json.loads(raw)["status"] == "ok"
