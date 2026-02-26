import json
from pathlib import Path
from typing import Dict, List

import yaml

from .config import FEATURE_MART_PATH, FEATURE_SET_PATH, POLICY_VERSION
from .metrics import record_data_freshness


def _read_jsonl(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_feature_mart_snapshot(raw_path: Path, output_path: Path = FEATURE_MART_PATH) -> Path:
    with FEATURE_SET_PATH.open("r", encoding="utf-8") as f:
        fs = yaml.safe_load(f)

    fs_version = fs["fs_version"]
    allowed = fs["features"]
    raw_rows = _read_jsonl(raw_path)

    latest_event_ts = None
    for row in raw_rows:
        event_ts = row.get("event_ts")
        if event_ts and (latest_event_ts is None or event_ts > latest_event_ts):
            latest_event_ts = event_ts
    record_data_freshness(dataset="raw_customers", latest_event_ts=latest_event_ts)

    snapshot_rows = []
    for row in raw_rows:
        snap = {
            "customer_id": row["customer_id"],
            "fs_version": fs_version,
            "policy_version": POLICY_VERSION,
        }
        for name in allowed:
            snap[name] = row[name]
        snap["is_employee_flag"] = bool(row.get("is_employee_flag", False))
        snap["do_not_contact_flag"] = bool(row.get("do_not_contact_flag", False))
        snap["opt_out_flag"] = bool(row.get("opt_out_flag", False))
        snap["legal_suppression_flag"] = bool(row.get("legal_suppression_flag", False))
        snap["region_code"] = str(row.get("region_code", "unknown"))
        snap["segment_id"] = str(row.get("segment_id", "unknown"))
        snap["product_line"] = str(row.get("product_line", "unknown"))
        snapshot_rows.append(snap)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in snapshot_rows:
            f.write(json.dumps(row) + "\n")
    return output_path
