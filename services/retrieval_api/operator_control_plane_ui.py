from __future__ import annotations

import json
from urllib.parse import quote_plus

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pipelines.minimal_slice import control_plane_registry
from pipelines.minimal_slice.control_plane_registry_action_audit import (
    record_registry_lifecycle_action,
)
from pipelines.minimal_slice.control_plane_promotion_governance import (
    record_promotion_decision,
    record_promotion_evidence,
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
from services.retrieval_api.operator_control_plane_governance import (
    evaluate_activation_governance,
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
    promotion_evaluation: dict[str, object] = {}
    if target_state == "active":
        promotion_evaluation = evaluate_activation_governance(
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            version_row=current_row,
        )
        if not bool(promotion_evaluation.get("promotion_ready")):
            decision = record_promotion_decision(
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                target_state=target_state,
                action=resolved_action_name,
                outcome="blocked",
                actor_id=principal.actor_id,
                evaluation=promotion_evaluation,
                note="Promotion blocked by governance evaluation.",
                details={"source_state": source_state},
            )
            message = _promotion_blocker_message(promotion_evaluation)
            record_registry_lifecycle_action(
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                action=resolved_action_name,
                target_state=target_state,
                outcome="failed",
                actor_id=principal.actor_id,
                details={
                    "from_state": source_state,
                    "error": message,
                    "governance_decision_id": decision.get("decision_id"),
                    "governance_blockers": promotion_evaluation.get("blockers", []),
                },
            )
            return render_detail_page(
                request=request,
                principal=principal,
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                error_message=message,
                status_code=400,
            )

    try:
        updated = control_plane_registry.transition_version_state(
            entity_type=registry_entity_type(resolved_entity_type),
            version_id=version_id,
            target_state=target_state,
        )
        if target_state == "active":
            decision = record_promotion_decision(
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                target_state=target_state,
                action=resolved_action_name,
                outcome="success",
                actor_id=principal.actor_id,
                evaluation=promotion_evaluation,
                note="Promotion completed.",
                details={
                    "source_state": source_state,
                    "to_state": updated.get("lifecycle_state"),
                },
            )
            governance_decision_id = decision.get("decision_id")
        else:
            governance_decision_id = None
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
                "governance_decision_id": governance_decision_id,
            },
        )
    except ValueError as exc:
        if target_state == "active":
            record_promotion_decision(
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                target_state=target_state,
                action=resolved_action_name,
                outcome="failed",
                actor_id=principal.actor_id,
                evaluation=promotion_evaluation,
                note="Promotion failed during lifecycle transition.",
                details={"source_state": source_state, "error": str(exc)},
            )
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
        if target_state == "active":
            record_promotion_decision(
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                target_state=target_state,
                action=resolved_action_name,
                outcome="failed",
                actor_id=principal.actor_id,
                evaluation=promotion_evaluation,
                note="Promotion failed due to unexpected error.",
                details={"source_state": source_state, "error": str(exc)},
            )
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

@OPERATOR_UI_ROUTER.post(
    "/operator/control-plane/versions/{entity_type}/{entity_key}/{version_id}/evidence",
    response_class=HTMLResponse,
)
def operator_control_plane_evidence_submit(
    request: Request,
    entity_type: str,
    entity_key: str,
    version_id: str,
    evidence_type: str = Form(...),
    status: str = Form(default="info"),
    note: str = Form(default=""),
    details_json: str = Form(default=""),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    resolved_entity_type = resolve_entity_type(entity_type)
    details = {}
    raw_details = details_json.strip()
    if raw_details:
        try:
            payload = json.loads(raw_details)
        except json.JSONDecodeError:
            return render_detail_page(
                request=request,
                principal=principal,
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                error_message="details_json must be valid JSON.",
                status_code=400,
            )
        if not isinstance(payload, dict):
            return render_detail_page(
                request=request,
                principal=principal,
                entity_type=resolved_entity_type,
                entity_key=entity_key,
                version_id=version_id,
                error_message="details_json must decode to a JSON object.",
                status_code=400,
            )
        details = payload

    try:
        record_promotion_evidence(
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            evidence_type=evidence_type,
            status=status,
            actor_id=principal.actor_id,
            note=note,
            details=details,
        )
    except ValueError as exc:
        return render_detail_page(
            request=request,
            principal=principal,
            entity_type=resolved_entity_type,
            entity_key=entity_key,
            version_id=version_id,
            error_message=str(exc),
            status_code=400,
        )

    notice = quote_plus(f"Evidence recorded: {evidence_type} status={status}")
    return RedirectResponse(
        url=(
            "/operator/control-plane/versions/"
            f"{resolved_entity_type}/{entity_key}/{version_id}?notice={notice}"
        ),
        status_code=303,
    )


def _promotion_blocker_message(evaluation: dict[str, object]) -> str:
    blockers = evaluation.get("blockers")
    if not isinstance(blockers, list):
        return "Promotion is blocked by governance evaluation."
    reasons = [
        str(blocker.get("message") or "").strip()
        for blocker in blockers
        if isinstance(blocker, dict) and str(blocker.get("message") or "").strip()
    ]
    if not reasons:
        return "Promotion is blocked by governance evaluation."
    return "Promotion blocked: " + "; ".join(reasons)
