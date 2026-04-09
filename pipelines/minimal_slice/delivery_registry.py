from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DELIVERY_REGISTRY_PATH = (
    ROOT / "governance" / "delivery" / "delivery_registry.yaml"
)


@dataclass(frozen=True)
class DeliveryTarget:
    delivery_target_id: str
    display_name: str
    implementation_status: str
    delivery_mode: str
    description: str


def _load_registry() -> dict[str, Any]:
    if not DELIVERY_REGISTRY_PATH.exists():
        raise ValueError(
            f"Required delivery registry artifact missing: {DELIVERY_REGISTRY_PATH}"
        )
    with DELIVERY_REGISTRY_PATH.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML object in {DELIVERY_REGISTRY_PATH}")
    return payload


def list_delivery_targets(*, include_planned: bool = True) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in _load_registry().get("delivery_targets", [])
        if isinstance(row, dict)
    ]
    if include_planned:
        return rows
    return [row for row in rows if row.get("implementation_status") == "implemented"]


def get_delivery_target(delivery_target_id: str) -> dict[str, Any]:
    for row in list_delivery_targets(include_planned=True):
        if row.get("delivery_target_id") == delivery_target_id:
            return row
    raise ValueError(f"Unknown delivery target: {delivery_target_id}")


def ensure_selectable_delivery_target(
    delivery_target_id: str,
    *,
    selection_kind: str,
) -> dict[str, Any]:
    row = get_delivery_target(delivery_target_id)
    status = str(row.get("implementation_status", "unknown"))
    if status != "implemented":
        raise ValueError(
            f"{selection_kind} delivery target is not implemented: "
            f"{delivery_target_id} (status={status})"
        )
    return row


def default_delivery_target_id() -> str:
    for row in list_delivery_targets(include_planned=False):
        target_id = row.get("delivery_target_id")
        if target_id:
            return str(target_id)
    raise ValueError("No implemented delivery targets found")
