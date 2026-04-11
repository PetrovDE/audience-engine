from __future__ import annotations

from typing import Any

from pipelines.minimal_slice import control_plane_registry
from pipelines.minimal_slice.control_plane_promotion_governance import (
    evaluate_promotion_readiness,
    list_promotion_evidence,
    list_recent_promotion_decisions,
)

PROMOTION_EVIDENCE_TYPES = (
    "validation_result",
    "readiness_result",
    "compatibility_check",
    "operator_note",
)


def _registry_entity_type(entity_type: str) -> str:
    if entity_type == "embedding_model_versions":
        return "embedding_providers"
    return entity_type


def _is_current_active_version(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    version_row: dict[str, Any],
) -> bool:
    explicit = version_row.get("is_current_active")
    if isinstance(explicit, bool):
        return explicit
    if str(version_row.get("lifecycle_state") or "").strip().lower() != "active":
        return False
    active_row = control_plane_registry.get_active_version(
        entity_type=_registry_entity_type(entity_type),
        entity_key=entity_key,
    )
    return str((active_row or {}).get("version_id") or "") == version_id


def evaluate_activation_governance(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    version_row: dict[str, Any] | None,
    evidence_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_row = version_row if isinstance(version_row, dict) else {}
    evidence = evidence_rows if isinstance(evidence_rows, list) else list_promotion_evidence(
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        limit=100,
    )
    if _is_current_active_version(
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        version_row=resolved_row,
    ):
        return {
            "entity_type": entity_type,
            "entity_key": entity_key,
            "version_id": version_id,
            "target_state": "active",
            "promotion_ready": True,
            "governance_applicability": "not_applicable_already_active",
            "activation_action_applicable": False,
            "blockers": [],
            "non_blocking": [],
            "checks": [
                {
                    "check": "activation_governance",
                    "required": False,
                    "status": "not_applicable",
                    "bucket": "info",
                    "message": (
                        "Activation governance is not applicable because this version "
                        "is already current active."
                    ),
                }
            ],
            "evidence_count": len(evidence),
            "latest_evidence": {},
        }
    evaluation = evaluate_promotion_readiness(
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        version_row=resolved_row,
        target_state="active",
        evidence_rows=evidence,
    )
    evaluation["governance_applicability"] = "applicable"
    evaluation["activation_action_applicable"] = True
    return evaluation


def promotion_governance_context(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
    version_row: dict[str, Any],
) -> dict[str, Any]:
    evidence_rows = list_promotion_evidence(
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        limit=25,
    )
    return {
        "promotion_readiness": evaluate_activation_governance(
            entity_type=entity_type,
            entity_key=entity_key,
            version_id=version_id,
            version_row=version_row,
            evidence_rows=evidence_rows,
        ),
        "promotion_evidence_rows": evidence_rows,
        "promotion_decision_rows": list_recent_promotion_decisions(
            entity_type=entity_type,
            entity_key=entity_key,
            version_id=version_id,
            limit=20,
        ),
        "promotion_evidence_types": PROMOTION_EVIDENCE_TYPES,
    }
