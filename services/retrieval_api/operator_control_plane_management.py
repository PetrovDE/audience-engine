from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import Response

from pipelines.minimal_slice import control_plane_registry
from pipelines.minimal_slice.control_plane_registry import validate_lifecycle_transition
from pipelines.minimal_slice.control_plane_registry_action_audit import (
    list_recent_registry_lifecycle_actions,
)
from services.retrieval_api.operator_control_plane_governance import (
    promotion_governance_context,
)
from services.retrieval_api.operator_ui import _base_context, templates

CONTROL_PLANE_LIST_PATH = "/operator/control-plane/versions"
DETAIL_LOOKUP_LIMIT = 500
_LIFECYCLE_ACTIONS = {
    "validate": {"label": "Validate", "target_state": "validated"},
    "activate": {"label": "Activate", "target_state": "active"},
    "deprecate": {"label": "Deprecate", "target_state": "deprecated"},
    "retire": {"label": "Retire", "target_state": "retired"},
}
_ENTITY_FAMILIES = {
    "feature_sets": {
        "label": "Feature Set Versions",
        "metadata_keys": ("owner", "domain", "description"),
    },
    "models": {
        "label": "Model Versions",
        "metadata_keys": ("model_family", "provider_type", "model_version"),
    },
    "embedding_model_versions": {
        "label": "Embedding Model Versions",
        "metadata_keys": ("provider_type", "provider_config_ref", "model_version"),
    },
    "policies": {
        "label": "Policy Versions",
        "metadata_keys": ("owner", "scope", "reason_code_binding"),
    },
    "audience_definitions": {
        "label": "Audience Definition Versions",
        "metadata_keys": ("intent", "owner", "segment_type"),
    },
}
_LEGACY_ENTITY_ALIASES = {
    "embedding_providers": "embedding_model_versions",
}


def resolve_entity_type(entity_type: str) -> str:
    resolved = entity_type.strip().lower()
    resolved = _LEGACY_ENTITY_ALIASES.get(resolved, resolved)
    if resolved in _ENTITY_FAMILIES:
        return resolved
    supported = ", ".join(sorted(_ENTITY_FAMILIES))
    raise ValueError(f"Unsupported entity_type: {entity_type}. Supported: {supported}")


def resolve_action(action_name: str) -> tuple[str, dict[str, str]]:
    resolved = action_name.strip().lower()
    action = _LIFECYCLE_ACTIONS.get(resolved)
    if action is None:
        supported = ", ".join(sorted(_LIFECYCLE_ACTIONS))
        raise ValueError(f"Unsupported lifecycle action: {action_name}. Supported: {supported}")
    return resolved, action


def load_version_detail(
    *,
    entity_type: str,
    entity_key: str,
    version_id: str,
) -> dict[str, Any] | None:
    rows = control_plane_registry.list_versions(
        entity_type=registry_entity_type(entity_type),
        entity_key=entity_key,
        limit=DETAIL_LOOKUP_LIMIT,
    )
    for row in rows:
        if str(row.get("version_id") or "") == version_id:
            resolved = dict(row)
            resolved["important_metadata"] = _important_metadata(entity_type, resolved)
            return resolved
    return None


def render_list_page(
    *,
    request: Request,
    principal: Any,
    entity_type: str,
    entity_key: str | None,
    limit: int,
    notice: str | None = None,
    error_message: str | None = None,
    status_code: int = 200,
) -> Response:
    rows: list[dict[str, Any]] = []
    selected_entity_type = "feature_sets"
    selected_family_label = _ENTITY_FAMILIES[selected_entity_type]["label"]
    errors: list[str] = []
    if error_message:
        errors.append(error_message)

    try:
        selected_entity_type = resolve_entity_type(entity_type)
        selected_family_label = _ENTITY_FAMILIES[selected_entity_type]["label"]
        rows = _load_list_rows(
            entity_type=selected_entity_type,
            entity_key=entity_key,
            limit=limit,
        )
    except ValueError as exc:
        errors.append(str(exc))

    context = _with_management_nav(
        _base_context(
            request=request,
            principal=principal,
            page_title="Control-Plane Versions",
            active_nav=CONTROL_PLANE_LIST_PATH,
            notice=notice,
            error_message="\n".join(errors) if errors else None,
        )
    )
    context.update(
        {
            "entity_options": _entity_nav_options(),
            "selected_entity_type": selected_entity_type,
            "selected_family_label": selected_family_label,
            "selected_entity_key": entity_key or "",
            "limit": limit,
            "rows": rows,
            "recent_actions": list_recent_registry_lifecycle_actions(limit=20),
        }
    )
    return templates.TemplateResponse(
        request,
        "operator/control_plane_registry_list.html",
        context,
        status_code=status_code,
    )


def render_detail_page(
    *,
    request: Request,
    principal: Any,
    entity_type: str,
    entity_key: str,
    version_id: str,
    notice: str | None = None,
    error_message: str | None = None,
    status_code: int = 200,
) -> Response:
    resolved_entity_type = resolve_entity_type(entity_type)
    version_row = load_version_detail(
        entity_type=resolved_entity_type,
        entity_key=entity_key,
        version_id=version_id,
    )
    if version_row is None:
        return render_list_page(
            request=request,
            principal=principal,
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            limit=50,
            error_message=(
                "Version not found for "
                f"entity_type={resolved_entity_type} entity_key={entity_key} "
                f"version_id={version_id}"
            ),
            status_code=404,
        )

    active_row = control_plane_registry.get_active_version(
        entity_type=registry_entity_type(resolved_entity_type),
        entity_key=entity_key,
    )
    active_version_id = str(active_row.get("version_id")) if active_row else None
    version_row["is_current_active"] = version_row["version_id"] == active_version_id
    governance = promotion_governance_context(
        entity_type=resolved_entity_type,
        entity_key=entity_key,
        version_id=version_id,
        version_row=version_row,
    )
    context = _with_management_nav(
        _base_context(
            request=request,
            principal=principal,
            page_title="Control-Plane Version Detail",
            active_nav=CONTROL_PLANE_LIST_PATH,
            notice=notice,
            error_message=error_message,
        )
    )
    context.update(
        {
            "entity_type": resolved_entity_type,
            "entity_label": _ENTITY_FAMILIES[resolved_entity_type]["label"],
            "entity_key": entity_key,
            "version_id": version_id,
            "version_row": version_row,
            "active_version_id": active_version_id,
            "action_controls": _action_controls(
                str(version_row.get("lifecycle_state") or "")
            ),
            "promotion_readiness": governance["promotion_readiness"],
            "promotion_evidence_rows": governance["promotion_evidence_rows"],
            "promotion_decision_rows": governance["promotion_decision_rows"],
            "promotion_evidence_types": governance["promotion_evidence_types"],
            "recent_actions": list_recent_registry_lifecycle_actions(
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                limit=25,
            ),
        }
    )
    return templates.TemplateResponse(
        request,
        "operator/control_plane_registry_detail.html",
        context,
        status_code=status_code,
    )


def _entity_nav_options() -> list[dict[str, str]]:
    return [
        {"entity_type": entity_type, "label": spec["label"]}
        for entity_type, spec in _ENTITY_FAMILIES.items()
    ]


def _with_management_nav(context: dict[str, Any]) -> dict[str, Any]:
    nav_items = list(context.get("nav_items", []))
    if not any(item.get("path") == CONTROL_PLANE_LIST_PATH for item in nav_items):
        nav_items.append(
            {"path": CONTROL_PLANE_LIST_PATH, "label": "Control-Plane Versions"}
        )
    context["nav_items"] = nav_items
    return context


def _important_metadata(entity_type: str, row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    resolved_payload = payload if isinstance(payload, dict) else {}
    result: dict[str, Any] = {}
    for key in _ENTITY_FAMILIES[entity_type]["metadata_keys"]:
        if key in resolved_payload and resolved_payload[key] not in ("", None):
            result[key] = resolved_payload[key]

    if entity_type == "embedding_model_versions":
        for key in ("provider_model_ref", "model_version_id", "capability"):
            if row.get(key):
                result[key] = row[key]
    if entity_type == "audience_definitions":
        for key in ("feature_set_version_id", "policy_version_id"):
            if row.get(key):
                result[key] = row[key]
    return result


def _load_list_rows(
    *,
    entity_type: str,
    entity_key: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = control_plane_registry.list_versions(
        entity_type=registry_entity_type(entity_type),
        entity_key=entity_key,
        limit=limit,
    )
    keys = sorted({str(row.get("entity_key") or "").strip() for row in rows if row})
    active_by_key: dict[str, str] = {}
    for key in keys:
        active_row = control_plane_registry.get_active_version(
            entity_type=registry_entity_type(entity_type),
            entity_key=key,
        )
        if active_row is not None:
            active_by_key[key] = str(active_row.get("version_id") or "")

    enriched: list[dict[str, Any]] = []
    for row in rows:
        resolved = dict(row)
        key = str(resolved.get("entity_key") or "").strip()
        version_id = str(resolved.get("version_id") or "").strip()
        resolved["is_current_active"] = version_id == active_by_key.get(key)
        resolved["important_metadata"] = _important_metadata(entity_type, resolved)
        enriched.append(resolved)
    return enriched


def _action_controls(current_state: str) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for action_name, action in _LIFECYCLE_ACTIONS.items():
        target_state = action["target_state"]
        allowed = False
        if current_state != target_state:
            try:
                validate_lifecycle_transition(current_state, target_state)
                allowed = True
            except ValueError:
                allowed = False
        controls.append(
            {
                "action_name": action_name,
                "label": action["label"],
                "target_state": target_state,
                "enabled": allowed,
            }
        )
    return controls


def registry_entity_type(entity_type: str) -> str:
    if entity_type == "embedding_model_versions":
        return "embedding_providers"
    return entity_type
