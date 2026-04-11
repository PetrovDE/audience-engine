from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pipelines.minimal_slice import control_plane_registry
from pipelines.minimal_slice.control_plane_registry_action_audit import (
    record_registry_lifecycle_action,
)
from services.retrieval_api.operator_control_plane_management import (
    CONTROL_PLANE_LIST_PATH,
    load_version_detail,
    registry_entity_type,
    render_detail_page,
    render_list_page,
    resolve_action,
    resolve_entity_type,
)
from services.retrieval_api.operator_ui import OPERATOR_UI_ROUTER, _require_signed_in_admin


@OPERATOR_UI_ROUTER.get(CONTROL_PLANE_LIST_PATH, response_class=HTMLResponse)
def operator_control_plane_list_page(
    request: Request,
    entity_type: str = Query(default="feature_sets"),
    entity_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    notice = request.query_params.get("notice")
    return render_list_page(
        request=request,
        principal=principal,
        entity_type=entity_type,
        entity_key=entity_key,
        limit=limit,
        notice=notice,
    )


@OPERATOR_UI_ROUTER.get(
    "/operator/control-plane/versions/{entity_type}/{entity_key}/{version_id}",
    response_class=HTMLResponse,
)
def operator_control_plane_detail_page(
    request: Request,
    entity_type: str,
    entity_key: str,
    version_id: str,
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    return render_detail_page(
        request=request,
        principal=principal,
        entity_type=entity_type,
        entity_key=entity_key,
        version_id=version_id,
        notice=request.query_params.get("notice"),
    )


@OPERATOR_UI_ROUTER.post(
    "/operator/control-plane/versions/{entity_type}/{entity_key}/{version_id}/actions/{action_name}",
    response_class=HTMLResponse,
)
def operator_control_plane_action_submit(
    request: Request,
    entity_type: str,
    entity_key: str,
    version_id: str,
    action_name: str,
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    resolved_entity_type = resolve_entity_type(entity_type)
    resolved_action_name, action = resolve_action(action_name)
    target_state = action["target_state"]
    current_row = load_version_detail(
        entity_type=resolved_entity_type,
        entity_key=entity_key,
        version_id=version_id,
    )
    source_state = None if current_row is None else current_row.get("lifecycle_state")

    try:
        updated = control_plane_registry.transition_version_state(
            entity_type=registry_entity_type(resolved_entity_type),
            version_id=version_id,
            target_state=target_state,
        )
        record_registry_lifecycle_action(
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            action=resolved_action_name,
            target_state=target_state,
            outcome="success",
            actor_id=principal.actor_id,
            details={
                "from_state": source_state,
                "to_state": updated.get("lifecycle_state"),
            },
        )
    except ValueError as exc:
        record_registry_lifecycle_action(
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            action=resolved_action_name,
            target_state=target_state,
            outcome="failed",
            actor_id=principal.actor_id,
            details={"from_state": source_state, "error": str(exc)},
        )
        return render_detail_page(
            request=request,
            principal=principal,
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            error_message=str(exc),
            status_code=400,
        )
    except Exception as exc:
        record_registry_lifecycle_action(
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            action=resolved_action_name,
            target_state=target_state,
            outcome="failed",
            actor_id=principal.actor_id,
            details={"from_state": source_state, "error": str(exc)},
        )
        return render_detail_page(
            request=request,
            principal=principal,
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            error_message=f"Lifecycle action failed: {exc}",
            status_code=500,
        )

    notice = quote_plus(
        f"{action['label']} completed. lifecycle_state={updated.get('lifecycle_state')}"
    )
    return RedirectResponse(
        url=(
            "/operator/control-plane/versions/"
            f"{resolved_entity_type}/{entity_key}/{version_id}?notice={notice}"
        ),
        status_code=303,
    )
