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
    assert any(row["export_id"] == "crm_salesforce_audience" for row in exports)
    assert any(row["profile_id"] == "local_snapshot_local_export" for row in profiles)
    assert any(row["profile_id"] == "salesforce_future_profile" for row in profiles)


def test_resolve_run_configuration_uses_defaults_and_request_override(
    monkeypatch, tmp_path
):
    state_path = tmp_path / "operator_state.json"
    monkeypatch.setattr(control_plane, "OPERATOR_STATE_PATH", state_path)

    defaults = control_plane.save_operator_defaults(
        default_policy_version="policy_credit_v1",
        default_integration_profile_id="local_snapshot_local_export",
    )
    assert defaults.default_policy_version == "policy_credit_v1"

    resolved_default = control_plane.resolve_run_configuration(
        policy_version=None,
        integration_profile_id=None,
    )
    assert resolved_default.policy_selection_source == "operator_default"
    assert resolved_default.integration_selection_source == "operator_default"
    assert resolved_default.integration_profile_id == "local_snapshot_local_export"

    resolved_request = control_plane.resolve_run_configuration(
        policy_version="policy_credit_v1",
        integration_profile_id="clickhouse_minio_export",
    )
    assert resolved_request.policy_selection_source == "request"
    assert resolved_request.integration_selection_source == "request"
    assert resolved_request.source_id == "clickhouse_feature_slice"
    assert resolved_request.export_id == "minio_jsonl"


def test_resolve_run_configuration_rejects_planned_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )

    with pytest.raises(ValueError, match="not implemented"):
        control_plane.resolve_run_configuration(
            policy_version="policy_credit_v1",
            integration_profile_id="salesforce_future_profile",
        )


def test_save_operator_defaults_rejects_unknown_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_plane, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json"
    )

    with pytest.raises(ValueError, match="Unknown policy_version"):
        control_plane.save_operator_defaults(default_policy_version="policy_missing_v1")


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
