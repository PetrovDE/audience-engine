from __future__ import annotations

import csv
from datetime import datetime, timezone

from pipelines.minimal_slice import delivery_targets
from pipelines.minimal_slice.delivery_contract import StagedAudienceRow


def _row(*, customer_id: str, rank: int) -> StagedAudienceRow:
    return StagedAudienceRow(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        campaign_id="camp_csv",
        customer_id=customer_id,
        status="approve",
        final_score=0.75,
        rank=rank,
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
        exported_ts=datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc),
        export_context={"reason_codes": []},
    )


def test_crm_csv_target_materializes_deterministic_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(delivery_targets, "DELIVERY_DIR", tmp_path)
    target = delivery_targets.CrmCsvFileTarget()
    rows = [_row(customer_id="cust_002", rank=2), _row(customer_id="cust_001", rank=1)]

    result = target.materialize(
        rows=rows,
        delivery_job_id="bcf4565c-2f93-41ab-98be-74a368932626",
    )

    assert result.rows_materialized == 2
    assert result.rows_written == 2
    assert result.rows_skipped_conflict == 0
    assert result.artifact_uri is not None

    artifact_path = (
        tmp_path
        / "crm_csv_file"
        / "run_id=7bf0c5be-f95c-4827-a5c4-6ee71f2807f2"
        / "delivery_job_id=bcf4565c-2f93-41ab-98be-74a368932626"
        / "crm_delivery_audience.csv"
    )
    assert artifact_path.exists()

    with artifact_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert [row["customer_id"] for row in rows] == ["cust_001", "cust_002"]
    assert [row["rank"] for row in rows] == ["1", "2"]


def test_crm_csv_target_uses_immutable_job_scoped_artifact_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(delivery_targets, "DELIVERY_DIR", tmp_path)
    target = delivery_targets.CrmCsvFileTarget()
    rows = [_row(customer_id="cust_001", rank=1)]

    first = target.materialize(
        rows=rows,
        delivery_job_id="11111111-1111-4111-8111-111111111111",
    )
    second = target.materialize(
        rows=rows,
        delivery_job_id="22222222-2222-4222-8222-222222222222",
    )

    assert first.artifact_uri != second.artifact_uri
    assert "delivery_job_id=11111111-1111-4111-8111-111111111111" in str(
        first.artifact_uri
    )
    assert "delivery_job_id=22222222-2222-4222-8222-222222222222" in str(
        second.artifact_uri
    )
