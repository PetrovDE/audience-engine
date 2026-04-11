from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .config import DATA_DIR

REGISTRY_ACTION_AUDIT_PATH = DATA_DIR / "control_plane" / "registry_action_audit.jsonl"


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def record_registry_lifecycle_action(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    action: str,
    target_state: str,
    outcome: str,
    actor_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    entry: dict[str, Any] = {
        "action_ts": datetime.now(timezone.utc).isoformat(),
        "entity_type": entity_type.strip().lower(),
        "entity_key": entity_key.strip(),
        "version_id": version_id.strip(),
        "action": action.strip().lower(),
        "target_state": target_state.strip().lower(),
        "outcome": outcome.strip().lower(),
        "actor_id": actor_id.strip(),
        "details": details if isinstance(details, dict) else {},
    }
    REGISTRY_ACTION_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_ACTION_AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def list_recent_registry_lifecycle_actions(
    *,
    entity_type: str | None = None,
    entity_key: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if not REGISTRY_ACTION_AUDIT_PATH.exists():
        return []

    filter_entity_type = _normalize_optional(entity_type)
    if filter_entity_type is not None:
        filter_entity_type = filter_entity_type.lower()
    filter_entity_key = _normalize_optional(entity_key)

    rows: list[dict[str, Any]] = []
    with REGISTRY_ACTION_AUDIT_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            try:
                entry = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue

            row_entity_type = str(entry.get("entity_type") or "").strip().lower()
            row_entity_key = str(entry.get("entity_key") or "").strip()
            if filter_entity_type is not None and row_entity_type != filter_entity_type:
                continue
            if filter_entity_key is not None and row_entity_key != filter_entity_key:
                continue
            rows.append(entry)

    rows.reverse()
    return rows[:limit]
