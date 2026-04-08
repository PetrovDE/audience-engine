from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REQUIRED_POLICY_INPUTS = ("blacklist", "communication_history")
OPTIONAL_POLICY_INPUTS: tuple[str, ...] = ()

POLICY_INPUT_SOURCE_MISSING = "POLICY_INPUT_SOURCE_MISSING"
POLICY_INPUT_SOURCE_UNREADABLE = "POLICY_INPUT_SOURCE_UNREADABLE"
POLICY_INPUT_SOURCE_INVALID = "POLICY_INPUT_SOURCE_INVALID"
POLICY_FAIL_CLOSED_REQUIRED_INPUT_REASON = "POLICY_FAIL_CLOSED_REQUIRED_INPUT"

_COMM_HISTORY_REQUIRED_FIELDS = ("customer_id", "campaign_id", "channel", "contact_ts")


@dataclass(frozen=True)
class PolicyRuntimeInputs:
    status: str
    source_status: Dict[str, Dict[str, Any]]
    errors: List[Dict[str, Any]]
    blacklist: set[str]
    history_by_customer: Dict[str, List[Dict[str, Any]]]


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _base_source_status(name: str, path: Path, required: bool) -> Dict[str, Any]:
    return {
        "source": name,
        "path": str(path),
        "required": required,
        "status": "ok",
        "records": 0,
    }


def _source_error(
    *,
    source: str,
    path: Path,
    code: str,
    detail: str,
    required: bool,
    line_number: int | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "source": source,
        "path": str(path),
        "required": required,
        "detail": detail,
    }
    if line_number is not None:
        payload["line_number"] = line_number
    return payload


def _load_blacklist(
    path: Path,
) -> tuple[Dict[str, Any], set[str], List[Dict[str, Any]]]:
    status = _base_source_status("blacklist", path, required=True)
    if not path.exists():
        status["status"] = "missing"
        return (
            status,
            set(),
            [
                _source_error(
                    source="blacklist",
                    path=path,
                    code=POLICY_INPUT_SOURCE_MISSING,
                    detail="required policy input file does not exist",
                    required=True,
                )
            ],
        )

    try:
        with path.open("r", encoding="utf-8") as f:
            rows = {line.strip() for line in f if line.strip()}
    except OSError as exc:
        status["status"] = "unreadable"
        return (
            status,
            set(),
            [
                _source_error(
                    source="blacklist",
                    path=path,
                    code=POLICY_INPUT_SOURCE_UNREADABLE,
                    detail=f"required policy input could not be read: {exc}",
                    required=True,
                )
            ],
        )
    except UnicodeDecodeError as exc:
        status["status"] = "invalid"
        return (
            status,
            set(),
            [
                _source_error(
                    source="blacklist",
                    path=path,
                    code=POLICY_INPUT_SOURCE_INVALID,
                    detail=f"required policy input has invalid text encoding: {exc}",
                    required=True,
                )
            ],
        )

    status["records"] = len(rows)
    return status, rows, []


def _load_comm_history(
    path: Path,
) -> tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    status = _base_source_status("communication_history", path, required=True)
    if not path.exists():
        status["status"] = "missing"
        return (
            status,
            {},
            [
                _source_error(
                    source="communication_history",
                    path=path,
                    code=POLICY_INPUT_SOURCE_MISSING,
                    detail="required policy input file does not exist",
                    required=True,
                )
            ],
        )

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    rows_count = 0
    errors: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as exc:
                    status["status"] = "invalid"
                    errors.append(
                        _source_error(
                            source="communication_history",
                            path=path,
                            code=POLICY_INPUT_SOURCE_INVALID,
                            detail=f"invalid JSON row: {exc}",
                            required=True,
                            line_number=line_number,
                        )
                    )
                    break
                if not isinstance(row, dict):
                    status["status"] = "invalid"
                    errors.append(
                        _source_error(
                            source="communication_history",
                            path=path,
                            code=POLICY_INPUT_SOURCE_INVALID,
                            detail="row must be a JSON object",
                            required=True,
                            line_number=line_number,
                        )
                    )
                    break

                missing_fields = [
                    field
                    for field in _COMM_HISTORY_REQUIRED_FIELDS
                    if row.get(field) in (None, "")
                ]
                if missing_fields:
                    status["status"] = "invalid"
                    errors.append(
                        _source_error(
                            source="communication_history",
                            path=path,
                            code=POLICY_INPUT_SOURCE_INVALID,
                            detail=(
                                "row missing required fields: "
                                + ", ".join(sorted(missing_fields))
                            ),
                            required=True,
                            line_number=line_number,
                        )
                    )
                    break

                if _parse_ts(row.get("contact_ts")) is None:
                    status["status"] = "invalid"
                    errors.append(
                        _source_error(
                            source="communication_history",
                            path=path,
                            code=POLICY_INPUT_SOURCE_INVALID,
                            detail="row has invalid contact_ts",
                            required=True,
                            line_number=line_number,
                        )
                    )
                    break

                customer_id = str(row["customer_id"])
                grouped.setdefault(customer_id, []).append(row)
                rows_count += 1
    except OSError as exc:
        status["status"] = "unreadable"
        return (
            status,
            {},
            [
                _source_error(
                    source="communication_history",
                    path=path,
                    code=POLICY_INPUT_SOURCE_UNREADABLE,
                    detail=f"required policy input could not be read: {exc}",
                    required=True,
                )
            ],
        )
    except UnicodeDecodeError as exc:
        status["status"] = "invalid"
        return (
            status,
            {},
            [
                _source_error(
                    source="communication_history",
                    path=path,
                    code=POLICY_INPUT_SOURCE_INVALID,
                    detail=f"required policy input has invalid text encoding: {exc}",
                    required=True,
                )
            ],
        )

    status["records"] = rows_count
    return status, grouped, errors


def load_policy_runtime_inputs(
    *,
    blacklist_path: Path,
    comm_history_path: Path,
) -> PolicyRuntimeInputs:
    source_status: Dict[str, Dict[str, Any]] = {}
    errors: List[Dict[str, Any]] = []

    blacklist_status, blacklist, blacklist_errors = _load_blacklist(blacklist_path)
    history_status, history_by_customer, history_errors = _load_comm_history(
        comm_history_path
    )

    source_status["blacklist"] = blacklist_status
    source_status["communication_history"] = history_status
    errors.extend(blacklist_errors)
    errors.extend(history_errors)

    has_required_failures = any(
        status.get("required") and status.get("status") != "ok"
        for status in source_status.values()
    )
    if errors:
        has_required_failures = True

    return PolicyRuntimeInputs(
        status="failed_closed" if has_required_failures else "ready",
        source_status=source_status,
        errors=errors,
        blacklist=blacklist if not has_required_failures else set(),
        history_by_customer=history_by_customer if not has_required_failures else {},
    )
