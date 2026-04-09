from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pipelines.minimal_slice import delivery_registry
from pipelines.minimal_slice.delivery_contract import (
    StagedAudienceRow,
    sort_staged_rows,
)


def _row(*, customer_id: str, rank: int) -> StagedAudienceRow:
    return StagedAudienceRow(
        run_id="7bf0c5be-f95c-4827-a5c4-6ee71f2807f2",
        campaign_id="camp_delivery_contract",
        customer_id=customer_id,
        status="approve",
        final_score=0.7,
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
        export_context={"reason_codes": ["NONE"]},
    )


def test_sort_staged_rows_is_stable_by_rank_then_customer_id():
    rows = [_row(customer_id="cust_b", rank=2), _row(customer_id="cust_a", rank=2)]
    rows.append(_row(customer_id="cust_z", rank=1))

    ordered = sort_staged_rows(rows)
    assert [row.customer_id for row in ordered] == ["cust_z", "cust_a", "cust_b"]


def test_delivery_registry_lists_implemented_and_planned_targets():
    targets = delivery_registry.list_delivery_targets(include_planned=True)
    target_ids = {row["delivery_target_id"] for row in targets}
    assert "crm_csv_file" in target_ids
    assert "crm_postgres_outbox" in target_ids
    assert "crm_api_future" in target_ids
    assert "acrm_api_future" in target_ids


def test_delivery_registry_rejects_planned_selection():
    with pytest.raises(ValueError, match="not implemented"):
        delivery_registry.ensure_selectable_delivery_target(
            "crm_api_future",
            selection_kind="Selected",
        )
