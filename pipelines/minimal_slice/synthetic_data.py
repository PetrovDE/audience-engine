import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from .config import BLACKLIST_PATH, COMM_HISTORY_PATH, RAW_PATH


def _random_credit_band(rng: random.Random) -> str:
    return rng.choices(["low", "medium", "high"], weights=[2, 5, 3], k=1)[0]


def _random_customer(idx: int, rng: random.Random) -> Dict:
    now = datetime.now(timezone.utc)
    tenure = rng.randint(1, 120)
    return {
        "customer_id": f"cust_{idx:05d}",
        "first_name": f"name_{idx}",
        "ssn_hash": f"hash_{idx:05d}",
        "event_ts": now.isoformat(),
        "customer_age_years": rng.randint(21, 78),
        "customer_tenure_months": tenure,
        "credit_score_band": _random_credit_band(rng),
        "delinquency_12m_count": rng.randint(0, 4),
        "utilization_ratio_avg_3m": round(rng.uniform(0.1, 0.95), 4),
        "card_spend_total_3m": round(rng.uniform(200, 9000), 2),
        "digital_engagement_score": round(rng.uniform(0, 1), 4),
        "is_employee_flag": rng.random() < 0.03,
        "do_not_contact_flag": rng.random() < 0.08,
    }


def _write_jsonl(path: Path, rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def generate_synthetic_data(
    customer_count: int = 200, seed: int = 42
) -> Dict[str, Path]:
    rng = random.Random(seed)
    customers = [_random_customer(i, rng) for i in range(customer_count)]

    blacklist_ids = [c["customer_id"] for c in customers if c["do_not_contact_flag"]]
    BLACKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with BLACKLIST_PATH.open("w", encoding="utf-8") as f:
        for cid in blacklist_ids[: max(1, len(blacklist_ids) // 2)]:
            f.write(cid + "\n")

    comm_rows = []
    today = datetime.now(timezone.utc)
    for c in customers:
        touches = rng.randint(0, 4)
        for i in range(touches):
            comm_rows.append(
                {
                    "customer_id": c["customer_id"],
                    "campaign_id": f"camp_{rng.randint(1, 4)}",
                    "channel": "email",
                    "contact_ts": (today - timedelta(hours=6 * i)).isoformat(),
                }
            )
    _write_jsonl(COMM_HISTORY_PATH, comm_rows)
    _write_jsonl(RAW_PATH, customers)

    return {
        "raw": RAW_PATH,
        "blacklist": BLACKLIST_PATH,
        "comm_history": COMM_HISTORY_PATH,
    }
