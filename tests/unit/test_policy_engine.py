import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from pipelines.minimal_slice.policy_engine import evaluate_policy


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_yaml(path, payload):
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)


def _policy_registry_and_reasons(tmp_path):
    registry_path = tmp_path / "policy_registry.yaml"
    reason_codes_path = tmp_path / "reason_codes.yaml"
    _write_yaml(
        reason_codes_path,
        {
            "version": 1,
            "codes": [
                {"code": "SUPPRESS_DNC", "class": "suppression", "message": "DNC"},
                {
                    "code": "SUPPRESS_OPTOUT",
                    "class": "suppression",
                    "message": "Opt-out",
                },
                {
                    "code": "SUPPRESS_LEGAL",
                    "class": "suppression",
                    "message": "Legal suppression",
                },
                {
                    "code": "SUPPRESS_EMPLOYEE",
                    "class": "suppression",
                    "message": "Employee",
                },
                {
                    "code": "ELIGIBILITY_TENURE_LT_3M",
                    "class": "eligibility",
                    "message": "Tenure",
                },
                {
                    "code": "RISK_DELINQ_GT_2",
                    "class": "risk",
                    "message": "Delinquency",
                },
                {
                    "code": "QUOTA_FREQ_CAP_7D",
                    "class": "quota",
                    "message": "7D cap",
                },
                {
                    "code": "QUOTA_FREQ_CAP_30D",
                    "class": "quota",
                    "message": "30D cap",
                },
                {
                    "code": "QUOTA_FREQ_CAP_90D",
                    "class": "quota",
                    "message": "90D cap",
                },
                {
                    "code": "QUOTA_REFUSAL_COOLDOWN",
                    "class": "quota",
                    "message": "cooldown",
                },
                {
                    "code": "CONFLICT_ACTIVE_CAMPAIGN",
                    "class": "conflict",
                    "message": "conflict",
                },
            ],
        },
    )
    _write_yaml(
        registry_path,
        {
            "version": 1,
            "policies": [
                {
                    "policy_version": "policy_test_v1",
                    "status": "active",
                    "rules": [
                        {
                            "id": "suppress_blacklist",
                            "priority": 10,
                            "when_jsonlogic": {"==": [{"var": "is_blacklisted"}, True]},
                            "action": "suppress",
                            "reason_code": "SUPPRESS_DNC",
                        },
                        {
                            "id": "suppress_optout",
                            "priority": 11,
                            "when_jsonlogic": {"==": [{"var": "opt_out_flag"}, True]},
                            "action": "suppress",
                            "reason_code": "SUPPRESS_OPTOUT",
                        },
                        {
                            "id": "suppress_legal",
                            "priority": 12,
                            "when_jsonlogic": {
                                "==": [{"var": "legal_suppression_flag"}, True]
                            },
                            "action": "suppress",
                            "reason_code": "SUPPRESS_LEGAL",
                        },
                        {
                            "id": "suppress_employee",
                            "priority": 20,
                            "when_jsonlogic": {
                                "==": [{"var": "is_employee_flag"}, True]
                            },
                            "action": "suppress",
                            "reason_code": "SUPPRESS_EMPLOYEE",
                        },
                        {
                            "id": "tenure",
                            "priority": 21,
                            "when_jsonlogic": {
                                "<": [{"var": "customer_tenure_months"}, 3]
                            },
                            "action": "suppress",
                            "reason_code": "ELIGIBILITY_TENURE_LT_3M",
                        },
                        {
                            "id": "delinq",
                            "priority": 22,
                            "when_jsonlogic": {">": [{"var": "delinquency_12m_count"}, 2]},
                            "action": "suppress",
                            "reason_code": "RISK_DELINQ_GT_2",
                        },
                        {
                            "id": "freq_7d",
                            "priority": 30,
                            "when_jsonlogic": {
                                ">=": [{"var": "contacts_last_7d"}, 2]
                            },
                            "action": "suppress",
                            "reason_code": "QUOTA_FREQ_CAP_7D",
                        },
                        {
                            "id": "freq_30d",
                            "priority": 31,
                            "when_jsonlogic": {
                                ">=": [{"var": "contacts_last_30d"}, 3]
                            },
                            "action": "suppress",
                            "reason_code": "QUOTA_FREQ_CAP_30D",
                        },
                        {
                            "id": "freq_90d",
                            "priority": 32,
                            "when_jsonlogic": {
                                ">=": [{"var": "contacts_last_90d"}, 4]
                            },
                            "action": "suppress",
                            "reason_code": "QUOTA_FREQ_CAP_90D",
                        },
                        {
                            "id": "cooldown",
                            "priority": 33,
                            "when_jsonlogic": {
                                "==": [{"var": "cooldown_after_refusal_active"}, True]
                            },
                            "action": "suppress",
                            "reason_code": "QUOTA_REFUSAL_COOLDOWN",
                        },
                        {
                            "id": "conflict",
                            "priority": 40,
                            "when_jsonlogic": {
                                "==": [{"var": "campaign_conflict_active"}, True]
                            },
                            "action": "suppress",
                            "reason_code": "CONFLICT_ACTIVE_CAMPAIGN",
                        },
                    ],
                }
            ],
        },
    )
    return registry_path, reason_codes_path


def _evaluate(tmp_path, candidates, comm_history_rows=None, blacklist_ids=None, **kwargs):
    registry_path, reason_codes_path = _policy_registry_and_reasons(tmp_path)
    blacklist_path = tmp_path / "blacklist.txt"
    blacklist_path.write_text("\n".join(blacklist_ids or []), encoding="utf-8")
    comm_history_path = tmp_path / "comm_history.jsonl"
    _write_jsonl(comm_history_path, comm_history_rows or [])
    return evaluate_policy(
        candidates=candidates,
        policy_version="policy_test_v1",
        policy_registry_path=registry_path,
        reason_codes_path=reason_codes_path,
        blacklist_path=blacklist_path,
        comm_history_path=comm_history_path,
        campaign_id="campaign_now",
        conflicting_campaign_ids={"campaign_other"},
        **kwargs,
    )


def test_policy_blacklist_optout_legal(tmp_path):
    result = _evaluate(
        tmp_path,
        candidates=[
            {"customer_id": "cust_black"},
            {"customer_id": "cust_opt", "opt_out_flag": True},
            {"customer_id": "cust_legal", "legal_suppression_flag": True},
        ],
        blacklist_ids=["cust_black"],
    )
    assert result["rejection_summary"]["SUPPRESS_DNC"] == 1
    assert result["rejection_summary"]["SUPPRESS_OPTOUT"] == 1
    assert result["rejection_summary"]["SUPPRESS_LEGAL"] == 1


def test_policy_eligibility_employee_tenure_delinquency(tmp_path):
    result = _evaluate(
        tmp_path,
        candidates=[
            {"customer_id": "cust_emp", "is_employee_flag": True},
            {"customer_id": "cust_tenure", "customer_tenure_months": 2},
            {"customer_id": "cust_delinq", "delinquency_12m_count": 3},
        ],
    )
    assert result["rejection_summary"]["SUPPRESS_EMPLOYEE"] == 1
    assert result["rejection_summary"]["ELIGIBILITY_TENURE_LT_3M"] == 1
    assert result["rejection_summary"]["RISK_DELINQ_GT_2"] == 1


def test_policy_frequency_caps_and_cooldown(tmp_path):
    now = datetime.now(timezone.utc)
    rows = [
        {"customer_id": "cust_freq", "channel": "email", "contact_ts": (now - timedelta(days=1)).isoformat()},
        {"customer_id": "cust_freq", "channel": "email", "contact_ts": (now - timedelta(days=2)).isoformat()},
        {"customer_id": "cust_freq", "channel": "email", "contact_ts": (now - timedelta(days=10)).isoformat()},
        {"customer_id": "cust_freq", "channel": "email", "contact_ts": (now - timedelta(days=60)).isoformat()},
        {
            "customer_id": "cust_cooldown",
            "channel": "email",
            "contact_ts": (now - timedelta(days=3)).isoformat(),
            "outcome": "refused",
        },
    ]
    result = _evaluate(
        tmp_path,
        candidates=[
            {"customer_id": "cust_freq"},
            {"customer_id": "cust_cooldown"},
        ],
        comm_history_rows=rows,
        refusal_cooldown_days=14,
    )
    assert result["rejection_summary"]["QUOTA_FREQ_CAP_7D"] == 1
    assert result["rejection_summary"]["QUOTA_FREQ_CAP_30D"] == 1
    assert result["rejection_summary"]["QUOTA_FREQ_CAP_90D"] == 1
    assert result["rejection_summary"]["QUOTA_REFUSAL_COOLDOWN"] == 1


def test_policy_campaign_conflict(tmp_path):
    now = datetime.now(timezone.utc)
    result = _evaluate(
        tmp_path,
        candidates=[{"customer_id": "cust_conflict"}],
        comm_history_rows=[
            {
                "customer_id": "cust_conflict",
                "campaign_id": "campaign_other",
                "active_flag": True,
                "outcome": "active",
                "channel": "email",
                "contact_ts": now.isoformat(),
            }
        ],
    )
    assert result["rejection_summary"]["CONFLICT_ACTIVE_CAMPAIGN"] == 1


def test_policy_requested_size_fill_logic(tmp_path):
    result = _evaluate(
        tmp_path,
        candidates=[
            {"customer_id": "cust_a", "score": 0.9},
            {"customer_id": "cust_b", "score": 0.7},
            {"customer_id": "cust_c", "score": 0.8},
        ],
        requested_size=2,
    )
    selected_ids = [row["customer_id"] for row in result["selected"]]
    assert selected_ids == ["cust_a", "cust_c"]
    assert result["summary"]["selected_count"] == 2


def test_policy_unknown_policy_version_errors(tmp_path):
    registry_path, reason_codes_path = _policy_registry_and_reasons(tmp_path)
    with pytest.raises(ValueError, match="Unknown policy_version"):
        evaluate_policy(
            candidates=[{"customer_id": "cust_x"}],
            policy_version="missing_policy",
            policy_registry_path=registry_path,
            reason_codes_path=reason_codes_path,
            blacklist_path=tmp_path / "blacklist.txt",
            comm_history_path=tmp_path / "comm_history.jsonl",
        )


def test_policy_rule_missing_reason_code_errors(tmp_path):
    registry_path, reason_codes_path = _policy_registry_and_reasons(tmp_path)
    with registry_path.open("r", encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    registry["policies"][0]["rules"][0]["when_jsonlogic"] = {
        "==": [{"var": "customer_id"}, "cust_err"]
    }
    registry["policies"][0]["rules"][0].pop("reason_code", None)
    _write_yaml(registry_path, registry)

    with pytest.raises(ValueError, match="missing reason_code"):
        evaluate_policy(
            candidates=[{"customer_id": "cust_err"}],
            policy_version="policy_test_v1",
            policy_registry_path=registry_path,
            reason_codes_path=reason_codes_path,
            blacklist_path=tmp_path / "blacklist.txt",
            comm_history_path=tmp_path / "comm_history.jsonl",
        )


def test_policy_rule_unknown_reason_code_errors(tmp_path):
    registry_path, reason_codes_path = _policy_registry_and_reasons(tmp_path)
    with registry_path.open("r", encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    registry["policies"][0]["rules"][0]["when_jsonlogic"] = {
        "==": [{"var": "customer_id"}, "cust_bad_code"]
    }
    registry["policies"][0]["rules"][0]["reason_code"] = "NOT_A_REAL_REASON"
    _write_yaml(registry_path, registry)

    with pytest.raises(ValueError, match="unknown reason_code"):
        evaluate_policy(
            candidates=[{"customer_id": "cust_bad_code"}],
            policy_version="policy_test_v1",
            policy_registry_path=registry_path,
            reason_codes_path=reason_codes_path,
            blacklist_path=tmp_path / "blacklist.txt",
            comm_history_path=tmp_path / "comm_history.jsonl",
        )


def test_policy_quota_not_triggered_under_threshold(tmp_path):
    now = datetime.now(timezone.utc)
    result = _evaluate(
        tmp_path,
        candidates=[{"customer_id": "cust_ok", "score": 0.5}],
        comm_history_rows=[
            {
                "customer_id": "cust_ok",
                "channel": "email",
                "contact_ts": (now - timedelta(days=2)).isoformat(),
            }
        ],
    )
    assert result["summary"]["approved_count"] == 1
    assert result["summary"]["rejected_count"] == 0
