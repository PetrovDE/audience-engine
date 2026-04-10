from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

LIFECYCLE_STATES = ("draft", "validated", "active", "deprecated", "retired")
_VALID_LIFECYCLE_STATES = set(LIFECYCLE_STATES)
_ALLOWED_STATE_TRANSITIONS = {
    "draft": {"validated"},
    "validated": {"draft", "active"},
    "active": {"deprecated"},
    "deprecated": {"active", "retired"},
    "retired": set(),
}

LINEAGE_MODE_RESOLVED = "resolved_versioned"
LINEAGE_MODE_DEGRADED = "degraded_unversioned"


@dataclass(frozen=True)
class RegistryEntitySpec:
    root_table: str
    version_table: str
    root_key_column: str
    version_parent_column: str
    required_reference_fields: tuple[str, ...]
    optional_reference_fields: tuple[str, ...]
    exposed_reference_fields: tuple[str, ...]


ENTITY_SPECS: dict[str, RegistryEntitySpec] = {
    "feature_sets": RegistryEntitySpec(
        root_table="feature_sets",
        version_table="feature_set_versions",
        root_key_column="feature_set_key",
        version_parent_column="feature_set_id",
        required_reference_fields=(),
        optional_reference_fields=(),
        exposed_reference_fields=(),
    ),
    "models": RegistryEntitySpec(
        root_table="models",
        version_table="model_versions",
        root_key_column="model_key",
        version_parent_column="model_id",
        required_reference_fields=(),
        optional_reference_fields=(),
        exposed_reference_fields=(),
    ),
    "embedding_providers": RegistryEntitySpec(
        root_table="embedding_providers",
        version_table="embedding_model_versions",
        root_key_column="provider_key",
        version_parent_column="embedding_provider_id",
        required_reference_fields=("model_version_id", "provider_model_ref"),
        optional_reference_fields=("capability",),
        exposed_reference_fields=(
            "model_version_id",
            "provider_model_ref",
            "capability",
        ),
    ),
    "policies": RegistryEntitySpec(
        root_table="policies",
        version_table="policy_versions",
        root_key_column="policy_key",
        version_parent_column="policy_id",
        required_reference_fields=(),
        optional_reference_fields=(),
        exposed_reference_fields=(),
    ),
    "audience_definitions": RegistryEntitySpec(
        root_table="audience_definitions",
        version_table="audience_definition_versions",
        root_key_column="audience_definition_key",
        version_parent_column="audience_definition_id",
        required_reference_fields=("feature_set_version_id",),
        optional_reference_fields=("policy_version_id",),
        exposed_reference_fields=("feature_set_version_id", "policy_version_id"),
    ),
}

UUID_REFERENCE_FIELDS = {
    "model_version_id",
    "feature_set_version_id",
    "policy_version_id",
    "audience_definition_version_id",
    "embedding_model_version_id",
}


class LineagePreconditionError(ValueError):
    """Raised when strict lineage resolution preconditions are not met."""


def normalize_required(value: str, *, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{field} is required")
    return resolved


def validate_uuid(value: str, *, field: str) -> str:
    candidate = normalize_required(value, field=field)
    try:
        UUID(candidate)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID: {candidate!r}") from exc
    return candidate


def entity_spec(entity_type: str) -> RegistryEntitySpec:
    key = normalize_required(entity_type, field="entity_type").lower()
    spec = ENTITY_SPECS.get(key)
    if spec is None:
        supported = ", ".join(sorted(ENTITY_SPECS))
        raise ValueError(
            f"Unsupported entity_type: {entity_type}. Supported: {supported}"
        )
    return spec


def validate_lifecycle_transition(current_state: str, target_state: str) -> None:
    current = normalize_required(current_state, field="current_state").lower()
    target = normalize_required(target_state, field="target_state").lower()
    if current not in _VALID_LIFECYCLE_STATES:
        raise ValueError(f"Unknown current_state: {current_state}")
    if target not in _VALID_LIFECYCLE_STATES:
        raise ValueError(f"Unknown target_state: {target_state}")
    if current == target:
        return
    allowed = _ALLOWED_STATE_TRANSITIONS[current]
    if target not in allowed:
        raise ValueError(f"Invalid lifecycle transition: {current} -> {target}")


def serialize_version_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            import json

            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}

    def to_iso(ts: Any) -> str | None:
        return ts.isoformat() if isinstance(ts, datetime) else None

    result: dict[str, Any] = {
        "version_id": str(row["version_id"]),
        "entity_key": str(row["entity_key"]),
        "version": str(row["version"]),
        "lifecycle_state": str(row["lifecycle_state"]),
        "payload": payload,
        "created_at": to_iso(row.get("created_at")),
        "updated_at": to_iso(row.get("updated_at")),
        "activated_at": to_iso(row.get("activated_at")),
    }
    for field in (
        "model_version_id",
        "feature_set_version_id",
        "policy_version_id",
        "provider_model_ref",
        "capability",
    ):
        if field in row and row[field] is not None:
            result[field] = str(row[field])
    return result
