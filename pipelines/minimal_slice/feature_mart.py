import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .config import FEATURE_MART_PATH, FEATURE_SET_PATH, POLICY_VERSION
from .metrics import record_data_freshness
from .storage import (
    minio_is_configured,
    read_feature_slice_from_clickhouse,
    write_feature_mart_parquet_to_minio,
)


def _read_jsonl(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _build_from_raw_rows(raw_rows: List[Dict], fs_version: str, allowed: List[str]) -> List[Dict]:
    snapshot_rows: List[Dict] = []
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
    return snapshot_rows


def _normalize_clickhouse_rows(
    rows: List[Dict[str, Any]], fs_version: str, allowed: List[str]
) -> List[Dict]:
    normalized: List[Dict] = []
    for row in rows:
        normalized_row = {
            "customer_id": row["customer_id"],
            "fs_version": str(row.get("fs_version", fs_version)),
            "policy_version": str(row.get("policy_version", POLICY_VERSION)),
        }
        for name in allowed:
            if name not in row:
                raise KeyError(f"ClickHouse row missing required feature: {name}")
            normalized_row[name] = row[name]
        normalized_row["is_employee_flag"] = bool(row.get("is_employee_flag", False))
        normalized_row["do_not_contact_flag"] = bool(row.get("do_not_contact_flag", False))
        normalized_row["opt_out_flag"] = bool(row.get("opt_out_flag", False))
        normalized_row["legal_suppression_flag"] = bool(
            row.get("legal_suppression_flag", False)
        )
        normalized_row["region_code"] = str(row.get("region_code", "unknown"))
        normalized_row["segment_id"] = str(row.get("segment_id", "unknown"))
        normalized_row["product_line"] = str(row.get("product_line", "unknown"))
        normalized.append(normalized_row)
    return normalized


def build_feature_mart_snapshot(
    raw_path: Path,
    output_path: Path = FEATURE_MART_PATH,
    *,
    source_mode: str = "snapshot",
    run_id: str | None = None,
) -> Path:
    with FEATURE_SET_PATH.open("r", encoding="utf-8") as f:
        fs = yaml.safe_load(f)

    fs_version = fs["fs_version"]
    allowed = fs["features"]
    resolved_source = source_mode.lower()
    if resolved_source == "clickhouse":
        clickhouse_rows = read_feature_slice_from_clickhouse()
        snapshot_rows = _normalize_clickhouse_rows(clickhouse_rows, fs_version, allowed)
        record_data_freshness(dataset="clickhouse_feature_slice", latest_event_ts=None)
    else:
        raw_rows = _read_jsonl(raw_path)
        latest_event_ts = None
        for row in raw_rows:
            event_ts = row.get("event_ts")
            if event_ts and (latest_event_ts is None or event_ts > latest_event_ts):
                latest_event_ts = event_ts
        record_data_freshness(dataset="raw_customers", latest_event_ts=latest_event_ts)
        snapshot_rows = _build_from_raw_rows(raw_rows, fs_version, allowed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in snapshot_rows:
            f.write(json.dumps(row) + "\n")

    if minio_is_configured():
        write_feature_mart_parquet_to_minio(
            rows=snapshot_rows,
            fs_version=fs_version,
            run_id=run_id,
        )
    return output_path
