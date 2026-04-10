from __future__ import annotations

from datetime import datetime, timezone

from pipelines.minimal_slice import delivery_runner
from pipelines.minimal_slice.delivery_contract import StagedAudienceRow


def _row() -> StagedAudienceRow:
    return StagedAudienceRow(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        campaign_id="camp_delivery",
        customer_id="cust_001",
        status="approve",
        final_score=0.88,
        rank=1,
        channel="email",
        policy_version="policy_credit_v1",
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        index_alias="audience-serving",
        index_generation="audience-serving-fs_credit_v1-abc12345",
        integration_profile_id="clickhouse_postgres_export",
        source_id="clickhouse_feature_slice",
        export_target_id="postgres_export_table",
        exported_ts=datetime(2026, 4, 9, 15, 0, tzinfo=timezone.utc),
        export_context={"reason_codes": []},
    )


def test_execute_delivery_for_run_reports_skipped_no_source_rows(monkeypatch):
    attempts: list[str] = []
    completed: dict[str, str] = {}

    class _FakeAdapter:
        def validate_config(self):
            return None

    monkeypatch.setattr(
        delivery_runner.delivery_registry,
        "ensure_selectable_delivery_target",
        lambda *args, **kwargs: {"delivery_target_id": "crm_csv_file"},
    )
    monkeypatch.setattr(
        delivery_runner.delivery_targets,
        "get_delivery_target_adapter",
        lambda target_id: _FakeAdapter(),
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "resolve_run_campaign_id",
        lambda run_id: "camp_delivery",
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "resolve_run_export_target_id",
        lambda run_id: "postgres_export_table",
    )
    monkeypatch.setattr(
        delivery_runner.control_plane,
        "list_export_targets",
        lambda include_planned=True: [
            {"export_id": "postgres_export_table", "config": {"write_postgres_table": True}}
        ],
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "fetch_staged_audience_rows",
        lambda run_id: [],
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "create_delivery_job",
        lambda **kwargs: {"delivery_job_id": "38a310f9-8416-4dfd-a1eb-83a2444ac250"},
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "append_delivery_attempt",
        lambda **kwargs: attempts.append(kwargs["attempt_status"]),
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "complete_delivery_job",
        lambda **kwargs: completed.update(
            {"status": kwargs["status"], "error_detail": kwargs["error_detail"]}
        ),
    )

    result = delivery_runner.execute_delivery_for_run(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        delivery_target_id="crm_csv_file",
        trigger_source="system:test",
        requested_by_role="system_internal",
        requested_by_id="system:test",
    )

    assert result["status"] == "skipped_no_source_rows"
    assert result["rows_delivered"] == 0
    assert attempts == ["pending", "skipped_no_source_rows"]
    assert completed["status"] == "skipped_no_source_rows"


def test_execute_delivery_for_run_routes_outbox_to_atomic_store(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeAdapter:
        def validate_config(self):
            return None

    monkeypatch.setattr(
        delivery_runner.delivery_registry,
        "ensure_selectable_delivery_target",
        lambda *args, **kwargs: {"delivery_target_id": "crm_postgres_outbox"},
    )
    monkeypatch.setattr(
        delivery_runner.delivery_targets,
        "get_delivery_target_adapter",
        lambda target_id: _FakeAdapter(),
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "resolve_run_campaign_id",
        lambda run_id: "camp_delivery",
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "resolve_run_export_target_id",
        lambda run_id: "postgres_export_table",
    )
    monkeypatch.setattr(
        delivery_runner.control_plane,
        "list_export_targets",
        lambda include_planned=True: [
            {"export_id": "postgres_export_table", "config": {"write_postgres_table": True}}
        ],
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "fetch_staged_audience_rows",
        lambda run_id: [_row()],
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "create_delivery_job",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("non-atomic create_delivery_job path should not be used")
        ),
    )
    monkeypatch.setattr(
        delivery_runner.delivery_store,
        "execute_crm_postgres_outbox_delivery_atomic",
        lambda **kwargs: captured.update(kwargs)
        or {
            "delivery_job_id": "96d343b3-f5bb-4a18-a95c-14072b0538de",
            "run_id": kwargs["run_id"],
            "campaign_id": kwargs["campaign_id"],
            "delivery_target_id": kwargs["delivery_target_id"],
            "status": "delivered",
            "source_row_count": 1,
            "rows_materialized": 1,
            "rows_delivered": 1,
            "rows_skipped_conflict": 0,
            "artifact_uri": None,
            "completed_at": "2026-04-09T00:00:00+00:00",
        },
    )

    result = delivery_runner.execute_delivery_for_run(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        delivery_target_id="crm_postgres_outbox",
        trigger_source="api:/test",
        requested_by_role="admin_operator",
        requested_by_id="admin:test",
    )

    assert result["status"] == "delivered"
    assert captured["delivery_target_id"] == "crm_postgres_outbox"
    assert len(captured["staged_rows"]) == 1
