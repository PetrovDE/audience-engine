import json

from pipelines.minimal_slice.policy_engine import evaluate_policy


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_evaluate_policy_applies_blacklist_and_frequency_cap(tmp_path):
    blacklist_path = tmp_path / "blacklist.txt"
    blacklist_path.write_text("cust_b\n", encoding="utf-8")

    comm_history_path = tmp_path / "comm_history.jsonl"
    _write_jsonl(
        comm_history_path,
        [
            {"customer_id": "cust_c", "channel": "email"},
            {"customer_id": "cust_c", "channel": "email"},
            {"customer_id": "cust_c", "channel": "sms"},
        ],
    )

    candidates = [
        {"customer_id": "cust_a"},
        {"customer_id": "cust_b"},
        {"customer_id": "cust_c"},
    ]

    result = evaluate_policy(
        candidates=candidates,
        blacklist_path=blacklist_path,
        comm_history_path=comm_history_path,
        daily_freq_cap=2,
    )

    decisions = {row["customer_id"]: row["decision"] for row in result["results"]}
    assert decisions["cust_a"] == "approve"
    assert decisions["cust_b"] == "reject"
    assert decisions["cust_c"] == "reject"

    summary = result["summary"]
    assert summary["total_candidates"] == 3
    assert summary["approved_count"] == 1
    assert summary["rejected_count"] == 2
    assert summary["reject_reason_counts"]["SUPPRESS_DNC"] == 1
    assert summary["reject_reason_counts"]["QUOTA_DAILY_CAMPAIGN_REACHED"] == 1


def test_evaluate_policy_allows_when_sources_missing(tmp_path):
    result = evaluate_policy(
        candidates=[{"customer_id": "cust_x"}],
        blacklist_path=tmp_path / "missing_blacklist.txt",
        comm_history_path=tmp_path / "missing_history.jsonl",
    )

    assert result["summary"]["approved_count"] == 1
    assert result["results"][0]["decision"] == "approve"
