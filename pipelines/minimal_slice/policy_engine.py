import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Set

from .metrics import record_policy_reject_reason


def _read_jsonl(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_blacklist(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _daily_frequency_counts(comm_history_path: Path) -> Counter:
    rows = _read_jsonl(comm_history_path)
    return Counter([row["customer_id"] for row in rows if row.get("channel") == "email"])


def evaluate_policy(
    candidates: List[Dict],
    blacklist_path: Path,
    comm_history_path: Path,
    daily_freq_cap: int = 2,
) -> Dict:
    blacklist = _read_blacklist(blacklist_path)
    freq_counts = _daily_frequency_counts(comm_history_path)

    reason_counts: Counter = Counter()
    results = []
    for item in candidates:
        cid = item["customer_id"]
        reasons = []
        if cid in blacklist:
            reasons.append(
                {
                    "reason_code": "SUPPRESS_DNC",
                    "reason_class": "suppression",
                    "message": "Customer present in blacklist suppression file.",
                    "rule_id": "suppress_blacklist",
                }
            )
        if freq_counts[cid] >= daily_freq_cap:
            reasons.append(
                {
                    "reason_code": "QUOTA_DAILY_CAMPAIGN_REACHED",
                    "reason_class": "quota",
                    "message": "Customer reached daily communication frequency cap.",
                    "rule_id": "frequency_cap_daily",
                }
            )

        for reason in reasons:
            reason_code = reason["reason_code"]
            reason_counts[reason_code] += 1
            record_policy_reject_reason(reason_code)

        decision = "reject" if reasons else "approve"
        results.append({"customer_id": cid, "decision": decision, "reasons": reasons})

    approved = [r for r in results if r["decision"] == "approve"]
    return {
        "summary": {
            "total_candidates": len(results),
            "approved_count": len(approved),
            "rejected_count": len(results) - len(approved),
            "reject_reason_counts": dict(reason_counts),
        },
        "results": results,
    }
