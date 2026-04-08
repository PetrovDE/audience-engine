from __future__ import annotations

from unittest.mock import Mock

from pipelines.minimal_slice.policy_decision_audit import (
    build_policy_decision_audit_rows,
    write_policy_decision_audit_rows,
)
from pipelines.version_bundle import VersionBundle


def _bundle() -> VersionBundle:
    return VersionBundle(
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
        index_alias="audience-serving",
        concrete_qdrant_collection="audience-serving-fs_credit_v1-abc12345",
        run_id="e0f62885-0dbc-4d53-b1d5-59fd0be558e2",
        campaign_id="camp_test",
    )


def test_build_policy_decision_audit_rows_contains_decision_lineage():
    policy_result = {
        "results": [
            {
                "customer_id": "cust_00001",
                "decision": "reject",
                "score": 0.12,
                "selected": False,
                "reasons": [
                    {
                        "reason_code": "SUPPRESS_DNC",
                        "reason_class": "suppression",
                        "message": "DNC",
                        "rule_id": "suppress_do_not_contact",
                    }
                ],
                "explanation": {"evaluation_mode": "rules"},
            }
        ]
    }
    rows = build_policy_decision_audit_rows(
        policy_result=policy_result,
        bundle=_bundle(),
        resolved_collection="customers_fs_credit_v1_8d_20260408010101",
        decision_ts="2026-04-08T01:01:01+00:00",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == "e0f62885-0dbc-4d53-b1d5-59fd0be558e2"
    assert row[1] == "camp_test"
    assert row[2] == "cust_00001"
    assert row[3] == "reject"
    assert row[4] == ["SUPPRESS_DNC"]
    assert row[5] == "policy_credit_v1"
    assert row[6] == "fs_credit_v1"
    assert row[7] == "fs_credit_v1+prompt_credit_v1+nomic-embed-text"
    assert row[8] == "nomic-embed-text"
    assert row[9] == "audience-serving"
    assert row[10] == "customers_fs_credit_v1_8d_20260408010101"


def test_write_policy_decision_audit_rows_executes_insert():
    cursor = Mock()
    rows = build_policy_decision_audit_rows(
        policy_result={
            "results": [
                {
                    "customer_id": "cust_00002",
                    "decision": "approve",
                    "score": 0.99,
                    "selected": True,
                    "reasons": [],
                    "explanation": {"evaluation_mode": "rules"},
                }
            ]
        },
        bundle=_bundle(),
        resolved_collection="customers_fs_credit_v1_8d_20260408020202",
        decision_ts="2026-04-08T02:02:02+00:00",
    )

    write_policy_decision_audit_rows(cursor, rows)

    cursor.executemany.assert_called_once()
    sql = cursor.executemany.call_args.args[0]
    payload_rows = cursor.executemany.call_args.args[1]
    assert "INSERT INTO policy_decision_audit" in sql
    assert len(payload_rows) == 1
