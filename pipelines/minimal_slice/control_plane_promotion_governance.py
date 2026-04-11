from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import DATA_DIR
from .control_plane_registry import validate_lifecycle_transition

PROMOTION_EVIDENCE_PATH = DATA_DIR / "control_plane" / "promotion_evidence.jsonl"
PROMOTION_DECISION_AUDIT_PATH = DATA_DIR / "control_plane" / "promotion_decision_audit.jsonl"

EVIDENCE_TYPES = ("validation_result", "readiness_result", "compatibility_check", "operator_note")
_PASS_STATUSES = {"pass", "passed", "success", "ready", "approved"}
_FAIL_STATUSES = {"fail", "failed", "error", "blocked", "not_ready"}
_COMPATIBILITY_REQUIRED_ENTITY_TYPES = {"models", "embedding_model_versions", "audience_definitions"}


def _req(value: str, *, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{field} is required")
    return resolved


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    resolved = value.strip()
    return resolved if resolved else None


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            try:
                row = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _normalize_evidence_type(value: str) -> str:
    evidence_type = _req(value, field="evidence_type").lower()
    if evidence_type not in EVIDENCE_TYPES:
        supported = ", ".join(EVIDENCE_TYPES)
        raise ValueError(f"Unsupported evidence_type: {value}. Supported: {supported}")
    return evidence_type


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    resolved_type = _req(entity_type, field="entity_type").lower()
    resolved_key = _req(entity_key, field="entity_key")
    resolved_version_id = _req(version_id, field="version_id")
    filtered = [
        row
        for row in rows
        if str(row.get("entity_type") or "").strip().lower() == resolved_type
        and str(row.get("entity_key") or "").strip() == resolved_key
        and str(row.get("version_id") or "").strip() == resolved_version_id
    ]
    filtered.reverse()
    return filtered[:limit]


def record_promotion_evidence(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    evidence_type: str,
    status: str,
    actor_id: str,
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "evidence_id": str(uuid4()),
        "recorded_ts": datetime.now(timezone.utc).isoformat(),
        "entity_type": _req(entity_type, field="entity_type").lower(),
        "entity_key": _req(entity_key, field="entity_key"),
        "version_id": _req(version_id, field="version_id"),
        "evidence_type": _normalize_evidence_type(evidence_type),
        "status": _req(status, field="status").lower(),
        "actor_id": _req(actor_id, field="actor_id"),
        "note": _opt(note),
        "details": details if isinstance(details, dict) else {},
    }
    _append_jsonl(PROMOTION_EVIDENCE_PATH, row)
    return row


def list_promotion_evidence(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _filter_rows(
        _read_jsonl(PROMOTION_EVIDENCE_PATH),
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        limit=limit,
    )


def record_promotion_decision(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    target_state: str,
    action: str,
    outcome: str,
    actor_id: str,
    evaluation: dict[str, Any],
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "decision_id": str(uuid4()),
        "decision_ts": datetime.now(timezone.utc).isoformat(),
        "entity_type": _req(entity_type, field="entity_type").lower(),
        "entity_key": _req(entity_key, field="entity_key"),
        "version_id": _req(version_id, field="version_id"),
        "target_state": _req(target_state, field="target_state").lower(),
        "action": _req(action, field="action").lower(),
        "outcome": _req(outcome, field="outcome").lower(),
        "actor_id": _req(actor_id, field="actor_id"),
        "note": _opt(note),
        "evaluation": evaluation if isinstance(evaluation, dict) else {},
        "details": details if isinstance(details, dict) else {},
    }
    _append_jsonl(PROMOTION_DECISION_AUDIT_PATH, row)
    return row


def list_recent_promotion_decisions(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    limit: int = 25,
) -> list[dict[str, Any]]:
    return _filter_rows(
        _read_jsonl(PROMOTION_DECISION_AUDIT_PATH),
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        limit=limit,
    )


def _status_bucket(status: str) -> str:
    if status in _PASS_STATUSES:
        return "pass"
    if status in _FAIL_STATUSES:
        return "fail"
    return "info"


def _latest_evidence_by_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        evidence_type = str(row.get("evidence_type") or "").strip().lower()
        if evidence_type in EVIDENCE_TYPES and evidence_type not in latest:
            latest[evidence_type] = row
    return latest


def _require_evidence(
    latest: dict[str, dict[str, Any]],
    *,
    evidence_type: str,
    message: str,
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    row = latest.get(evidence_type)
    if row is None:
        blockers.append({"code": f"missing_{evidence_type}", "message": f"{message} evidence is missing."})
        return {
            "check": evidence_type,
            "required": True,
            "status": "missing",
            "bucket": "fail",
            "message": f"{message} evidence is required.",
        }
    status = str(row.get("status") or "").strip().lower()
    bucket = _status_bucket(status)
    if bucket != "pass":
        blockers.append(
            {
                "code": f"{evidence_type}_not_passed",
                "message": f"{message} evidence has non-passing status={status!r}.",
            }
        )
    return {
        "check": evidence_type,
        "required": True,
        "status": status,
        "bucket": bucket,
        "message": message,
        "evidence_id": row.get("evidence_id"),
    }


def evaluate_promotion_readiness(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    version_row: dict[str, Any] | None,
    target_state: str = "active",
    evidence_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_entity_type = _req(entity_type, field="entity_type").lower()
    resolved_target_state = _req(target_state, field="target_state").lower()
    evidence = evidence_rows or list_promotion_evidence(
        entity_type=resolved_entity_type,
        entity_key=entity_key,
        version_id=version_id,
        limit=100,
    )
    latest = _latest_evidence_by_type(evidence)

    blockers: list[dict[str, str]] = []
    non_blocking: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    state = str((version_row or {}).get("lifecycle_state") or "").strip().lower()
    if not state:
        blockers.append(
            {
                "code": "missing_lifecycle_state",
                "message": "Version lifecycle state is missing; cannot evaluate promotion.",
            }
        )
        checks.append(
            {
                "check": "lifecycle_transition",
                "required": True,
                "status": "missing",
                "bucket": "fail",
                "message": "Version lifecycle state is missing.",
            }
        )
    else:
        try:
            validate_lifecycle_transition(state, resolved_target_state)
            checks.append(
                {
                    "check": "lifecycle_transition",
                    "required": True,
                    "status": "passed",
                    "bucket": "pass",
                    "message": f"Lifecycle transition {state} -> {resolved_target_state} is allowed.",
                }
            )
        except ValueError as exc:
            blockers.append({"code": "invalid_lifecycle_transition", "message": str(exc)})
            checks.append(
                {
                    "check": "lifecycle_transition",
                    "required": True,
                    "status": "failed",
                    "bucket": "fail",
                    "message": str(exc),
                }
            )

    checks.append(
        _require_evidence(
            latest,
            evidence_type="validation_result",
            message="Validation result",
            blockers=blockers,
        )
    )
    checks.append(
        _require_evidence(
            latest,
            evidence_type="readiness_result",
            message="Readiness result",
            blockers=blockers,
        )
    )
    if resolved_entity_type in _COMPATIBILITY_REQUIRED_ENTITY_TYPES:
        checks.append(
            _require_evidence(
                latest,
                evidence_type="compatibility_check",
                message="Compatibility/provider check",
                blockers=blockers,
            )
        )
    if resolved_entity_type == "embedding_model_versions":
        if not (version_row or {}).get("provider_model_ref"):
            blockers.append({"code": "missing_provider_model_ref", "message": "Embedding model version is missing provider_model_ref."})
        if not (version_row or {}).get("model_version_id"):
            blockers.append({"code": "missing_model_version_id", "message": "Embedding model version is missing model_version_id."})
    if resolved_entity_type == "audience_definitions" and not (version_row or {}).get("feature_set_version_id"):
        blockers.append(
            {
                "code": "missing_feature_set_version_id",
                "message": "Audience definition version must reference feature_set_version_id.",
            }
        )
    if "operator_note" not in latest:
        non_blocking.append({"code": "missing_operator_note", "message": "Operator rationale note is missing."})

    return {
        "entity_type": resolved_entity_type,
        "entity_key": _req(entity_key, field="entity_key"),
        "version_id": _req(version_id, field="version_id"),
        "target_state": resolved_target_state,
        "promotion_ready": len(blockers) == 0,
        "blockers": blockers,
        "non_blocking": non_blocking,
        "checks": checks,
        "evidence_count": len(evidence),
        "latest_evidence": latest,
    }
