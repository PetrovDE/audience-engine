from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from pipelines.minimal_slice import (
    control_plane,
    delivery_runner,
    integrations,
    lifecycle_service,
    run_flow,
)
from pipelines.minimal_slice.data_quality import DataQualityError
from pipelines.minimal_slice.policy_decision_audit import fetch_policy_decision_audit
from services.retrieval_api.auth import (
    API_KEY_HEADER,
    Principal,
    rbac_is_configured,
    resolve_admin_principal_from_api_key,
)

MODULE_DIR = Path(__file__).resolve().parent
OPERATOR_TEMPLATE_DIR = MODULE_DIR / "templates"
OPERATOR_STATIC_DIR = MODULE_DIR / "static"
OPERATOR_SESSION_COOKIE = "ae_operator_api_key"
DEFAULT_PAGE_SIZE = 20
OPERATOR_DASHBOARD_PATH = "/operator/dashboard"

OPERATOR_UI_ROUTER = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(OPERATOR_TEMPLATE_DIR))


def _json_pretty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, sort_keys=True, default=str)


templates.env.filters["json_pretty"] = _json_pretty


NAV_ITEMS = [
    {"path": "/operator/dashboard", "label": "Dashboard"},
    {"path": "/operator/defaults", "label": "Defaults"},
    {"path": "/operator/trigger-run", "label": "Trigger Run"},
    {"path": "/operator/recent-runs", "label": "Recent Runs"},
    {"path": "/operator/delivery", "label": "Delivery"},
    {"path": "/operator/explain-audit", "label": "Explain / Audit"},
    {"path": "/operator/readiness", "label": "Integrations / Readiness"},
]


def _safe_next_path(candidate: str | None) -> str:
    if not candidate:
        return OPERATOR_DASHBOARD_PATH
    if not candidate.startswith("/operator"):
        return OPERATOR_DASHBOARD_PATH
    return candidate


def _signed_in_principal(request: Request) -> Principal | None:
    cookie_key = request.cookies.get(OPERATOR_SESSION_COOKIE)
    header_key = request.headers.get(API_KEY_HEADER)
    api_key = cookie_key or header_key
    return resolve_admin_principal_from_api_key(api_key)


def _redirect_to_login(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    encoded = quote(next_path, safe="/?=&")
    return RedirectResponse(url=f"/operator/login?next={encoded}", status_code=303)


def _require_signed_in_admin(request: Request) -> Principal | RedirectResponse:
    principal = _signed_in_principal(request)
    if principal is None:
        return _redirect_to_login(request)
    return principal


def _base_context(
    *,
    request: Request,
    principal: Principal | None,
    page_title: str,
    active_nav: str,
    notice: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "request": request,
        "page_title": page_title,
        "active_nav": active_nav,
        "nav_items": NAV_ITEMS,
        "principal": principal,
        "notice": notice,
        "error_message": error_message,
    }


def _collect_model_and_readiness() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []

    model: dict[str, Any] = {}
    try:
        model = control_plane.describe_operational_model()
    except Exception as exc:
        errors.append(f"control-plane model unavailable: {exc}")

    try:
        defaults = control_plane.load_operator_defaults()
    except Exception as exc:
        defaults = None
        errors.append(f"operator defaults unavailable: {exc}")

    try:
        integrations_payload = integrations.annotate_runtime_readiness(
            sources=control_plane.list_source_connectors(include_planned=True),
            exports=control_plane.list_export_targets(include_planned=True),
            profiles=control_plane.list_integration_profiles(include_planned=True),
        )
    except Exception as exc:
        integrations_payload = {"sources": [], "exports": [], "profiles": []}
        errors.append(f"integration readiness unavailable: {exc}")

    try:
        delivery_targets = delivery_runner.list_delivery_targets(include_planned=True)
    except Exception as exc:
        delivery_targets = []
        errors.append(f"delivery readiness unavailable: {exc}")

    result = {
        "model": model,
        "defaults": defaults,
        "integrations_payload": integrations_payload,
        "delivery_targets": delivery_targets,
    }
    return result, errors


def _load_defaults_form_state() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        defaults = control_plane.load_operator_defaults()
    except Exception as exc:
        defaults = None
        errors.append(f"operator defaults unavailable: {exc}")

    try:
        policies = control_plane.list_policies()
    except Exception as exc:
        policies = []
        errors.append(f"policies unavailable: {exc}")

    try:
        readiness = integrations.annotate_runtime_readiness(
            sources=control_plane.list_source_connectors(include_planned=True),
            exports=control_plane.list_export_targets(include_planned=True),
            profiles=control_plane.list_integration_profiles(include_planned=True),
        )
        profiles = readiness.get("profiles", [])
    except Exception as exc:
        profiles = []
        errors.append(f"integration profiles unavailable: {exc}")

    try:
        delivery_targets = delivery_runner.list_delivery_targets(include_planned=True)
    except Exception as exc:
        delivery_targets = []
        errors.append(f"delivery targets unavailable: {exc}")

    return {
        "defaults": defaults,
        "policies": policies,
        "profiles": profiles,
        "delivery_targets": delivery_targets,
    }, errors


def _parse_optional_form_value(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = value.strip()
    return parsed if parsed else None


def _coerce_positive_int(
    value: str,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a whole number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}.")
    return parsed


@OPERATOR_UI_ROUTER.get("/operator")
def operator_root() -> RedirectResponse:
    return RedirectResponse(url=OPERATOR_DASHBOARD_PATH, status_code=303)


@OPERATOR_UI_ROUTER.get("/operator/login", response_class=HTMLResponse)
def operator_login_page(
    request: Request,
    next: str = Query(default=OPERATOR_DASHBOARD_PATH),
) -> Response:
    principal = _signed_in_principal(request)
    if principal is not None:
        return RedirectResponse(url=_safe_next_path(next), status_code=303)
    context = {
        "request": request,
        "next_path": _safe_next_path(next),
        "rbac_configured": rbac_is_configured(),
        "error_message": None,
    }
    return templates.TemplateResponse(request, "operator/login.html", context)


@OPERATOR_UI_ROUTER.post("/operator/login", response_class=HTMLResponse)
def operator_login_submit(
    request: Request,
    api_key: str = Form(...),
    next: str = Form(default=OPERATOR_DASHBOARD_PATH),
) -> Response:
    safe_next = _safe_next_path(next)
    if not rbac_is_configured():
        return templates.TemplateResponse(
            request,
            "operator/login.html",
            {
                "request": request,
                "next_path": safe_next,
                "rbac_configured": False,
                "error_message": (
                    "RBAC is not configured. Set AE_ADMIN_API_KEYS to use "
                    "the operator console."
                ),
            },
            status_code=403,
        )

    principal = resolve_admin_principal_from_api_key(api_key.strip())
    if principal is None:
        return templates.TemplateResponse(
            request,
            "operator/login.html",
            {
                "request": request,
                "next_path": safe_next,
                "rbac_configured": True,
                "error_message": (
                    "Invalid admin API key. Use a key configured in "
                    "AE_ADMIN_API_KEYS."
                ),
            },
            status_code=401,
        )

    response = RedirectResponse(url=safe_next, status_code=303)
    response.set_cookie(
        key=OPERATOR_SESSION_COOKIE,
        value=api_key.strip(),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=8 * 60 * 60,
    )
    return response


@OPERATOR_UI_ROUTER.post("/operator/logout")
def operator_logout() -> RedirectResponse:
    response = RedirectResponse(url="/operator/login", status_code=303)
    response.delete_cookie(OPERATOR_SESSION_COOKIE)
    return response


@OPERATOR_UI_ROUTER.get("/operator/dashboard", response_class=HTMLResponse)
def operator_dashboard(request: Request) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    payload, data_errors = _collect_model_and_readiness()
    integrations_payload = payload["integrations_payload"]
    delivery_targets = payload["delivery_targets"]
    profiles = integrations_payload.get("profiles", [])
    defaults = payload["defaults"]

    default_profile = None
    default_delivery_target = None
    if defaults is not None:
        for row in profiles:
            if row.get("profile_id") == defaults.default_integration_profile_id:
                default_profile = row
                break
        for row in delivery_targets:
            if row.get("delivery_target_id") == defaults.default_delivery_target_id:
                default_delivery_target = row
                break

    context = _base_context(
        request=request,
        principal=principal,
        page_title="Dashboard",
        active_nav="/operator/dashboard",
        error_message="\n".join(data_errors) if data_errors else None,
    )
    context.update(
        {
            "model": payload["model"],
            "defaults": defaults,
            "integrations_payload": integrations_payload,
            "delivery_targets": delivery_targets,
            "default_profile": default_profile,
            "default_delivery_target": default_delivery_target,
        }
    )
    return templates.TemplateResponse(request, "operator/dashboard.html", context)


def _render_defaults_page(
    *,
    request: Request,
    principal: Principal,
    notice: str | None = None,
    error_message: str | None = None,
) -> Response:
    state, data_errors = _load_defaults_form_state()
    all_errors = []
    if error_message:
        all_errors.append(error_message)
    all_errors.extend(data_errors)
    context = _base_context(
        request=request,
        principal=principal,
        page_title="Defaults",
        active_nav="/operator/defaults",
        notice=notice,
        error_message="\n".join(all_errors) if all_errors else None,
    )
    context.update(state)
    return templates.TemplateResponse(request, "operator/defaults.html", context)


@OPERATOR_UI_ROUTER.get("/operator/defaults", response_class=HTMLResponse)
def operator_defaults_page(
    request: Request,
    notice: str | None = Query(default=None),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    return _render_defaults_page(request=request, principal=principal, notice=notice)


@OPERATOR_UI_ROUTER.post("/operator/defaults", response_class=HTMLResponse)
def operator_defaults_submit(
    request: Request,
    default_policy_version: str = Form(...),
    default_integration_profile_id: str = Form(...),
    default_delivery_target_id: str = Form(...),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    try:
        control_plane.save_operator_defaults(
            default_policy_version=default_policy_version.strip(),
            default_integration_profile_id=default_integration_profile_id.strip(),
            default_delivery_target_id=default_delivery_target_id.strip(),
        )
    except ValueError as exc:
        return _render_defaults_page(
            request=request,
            principal=principal,
            error_message=str(exc),
        )
    return RedirectResponse(
        url="/operator/defaults?notice=Defaults+updated",
        status_code=303,
    )


def _load_trigger_options() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        defaults = control_plane.load_operator_defaults()
    except Exception as exc:
        defaults = None
        errors.append(f"operator defaults unavailable: {exc}")

    try:
        policies = control_plane.list_policies()
    except Exception as exc:
        policies = []
        errors.append(f"policies unavailable: {exc}")

    try:
        profiles = control_plane.list_integration_profiles(include_planned=True)
    except Exception as exc:
        profiles = []
        errors.append(f"integration profiles unavailable: {exc}")

    try:
        delivery_targets = delivery_runner.list_delivery_targets(include_planned=True)
    except Exception as exc:
        delivery_targets = []
        errors.append(f"delivery targets unavailable: {exc}")

    return {
        "defaults": defaults,
        "policies": policies,
        "profiles": profiles,
        "delivery_targets": delivery_targets,
    }, errors


def _render_trigger_page(
    *,
    request: Request,
    principal: Principal,
    trigger_result: dict[str, Any] | None = None,
    notice: str | None = None,
    error_message: str | None = None,
) -> Response:
    options, data_errors = _load_trigger_options()
    all_errors = []
    if error_message:
        all_errors.append(error_message)
    all_errors.extend(data_errors)
    context = _base_context(
        request=request,
        principal=principal,
        page_title="Trigger Run",
        active_nav="/operator/trigger-run",
        notice=notice,
        error_message="\n".join(all_errors) if all_errors else None,
    )
    context.update(options)
    context["trigger_result"] = trigger_result
    return templates.TemplateResponse(request, "operator/trigger_run.html", context)


@OPERATOR_UI_ROUTER.get("/operator/trigger-run", response_class=HTMLResponse)
def operator_trigger_run_page(
    request: Request,
    notice: str | None = Query(default=None),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    return _render_trigger_page(request=request, principal=principal, notice=notice)


@OPERATOR_UI_ROUTER.post("/operator/trigger-run", response_class=HTMLResponse)
def operator_trigger_run_submit(
    request: Request,
    campaign_id: str = Form(...),
    requested_size: str = Form(default="20"),
    policy_version_override: str = Form(default=""),
    integration_profile_id_override: str = Form(default=""),
    delivery_target_id_override: str = Form(default=""),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    campaign = campaign_id.strip()
    if not campaign:
        return _render_trigger_page(
            request=request,
            principal=principal,
            error_message="campaign_id is required.",
        )

    try:
        size = _coerce_positive_int(
            requested_size,
            field_name="requested_size",
            minimum=1,
            maximum=500,
        )
    except ValueError as exc:
        return _render_trigger_page(
            request=request,
            principal=principal,
            error_message=str(exc),
        )

    policy_override = _parse_optional_form_value(policy_version_override)
    profile_override = _parse_optional_form_value(integration_profile_id_override)
    delivery_override = _parse_optional_form_value(delivery_target_id_override)

    try:
        summary = run_flow.run_minimal_vertical_slice(
            campaign_id=campaign,
            policy_version=policy_override,
            integration_profile_id=profile_override,
            delivery_target_id=delivery_override,
            requested_size=size,
        )
    except DataQualityError as exc:
        return _render_trigger_page(
            request=request,
            principal=principal,
            error_message=json.dumps(exc.to_dict(), indent=2),
        )
    except ValueError as exc:
        return _render_trigger_page(
            request=request,
            principal=principal,
            error_message=str(exc),
        )
    except Exception as exc:
        return _render_trigger_page(
            request=request,
            principal=principal,
            error_message=f"Run failed: {exc}",
        )

    versions = summary.get("versions", {})
    run_id = versions.get("run_id") if isinstance(versions, dict) else None
    notice = "Run finished."
    if run_id:
        notice = f"Run finished. run_id={run_id}"
    return _render_trigger_page(
        request=request,
        principal=principal,
        trigger_result=summary,
        notice=notice,
    )


@OPERATOR_UI_ROUTER.get("/operator/recent-runs", response_class=HTMLResponse)
def operator_recent_runs_page(
    request: Request,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=200),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    try:
        rows = control_plane.list_recent_run_events(limit=limit)
        error_message = None
    except Exception as exc:
        rows = []
        error_message = str(exc)

    context = _base_context(
        request=request,
        principal=principal,
        page_title="Recent Runs",
        active_nav="/operator/recent-runs",
        error_message=error_message,
    )
    context["runs"] = rows
    context["limit"] = limit
    return templates.TemplateResponse(request, "operator/recent_runs.html", context)


@OPERATOR_UI_ROUTER.get("/operator/delivery", response_class=HTMLResponse)
def operator_delivery_page(
    request: Request,
    limit_jobs: int = Query(default=20, ge=1, le=200),
    limit_attempts: int = Query(default=50, ge=1, le=500),
    run_id: str | None = Query(default=None),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    errors: list[str] = []

    try:
        jobs = delivery_runner.list_recent_delivery_jobs(limit=limit_jobs)
    except Exception as exc:
        jobs = []
        errors.append(f"recent delivery jobs unavailable: {exc}")

    run_filter = _parse_optional_form_value(run_id)
    valid_run_filter = run_filter
    if run_filter:
        try:
            UUID(run_filter)
        except ValueError:
            valid_run_filter = None
            errors.append(f"Invalid run_id format (expected UUID): {run_filter}")

    try:
        attempts = delivery_runner.list_recent_delivery_attempts(
            limit=limit_attempts,
            run_id=valid_run_filter,
        )
    except Exception as exc:
        attempts = []
        errors.append(f"delivery attempts unavailable: {exc}")

    summary_for_run = None
    records_for_run: list[dict[str, Any]] = []
    if valid_run_filter:
        try:
            summary_for_run = delivery_runner.latest_delivery_summary_for_run(
                valid_run_filter
            )
        except Exception as exc:
            errors.append(
                "delivery summary unavailable for "
                f"run_id={valid_run_filter}: {exc}"
            )
        try:
            records_for_run = delivery_runner.list_delivery_records_for_run(
                run_id=valid_run_filter,
                limit=200,
            )
        except Exception as exc:
            errors.append(
                "delivery records unavailable for "
                f"run_id={valid_run_filter}: {exc}"
            )

    context = _base_context(
        request=request,
        principal=principal,
        page_title="Delivery",
        active_nav="/operator/delivery",
        error_message="\n".join(errors) if errors else None,
    )
    context.update(
        {
            "jobs": jobs,
            "attempts": attempts,
            "run_filter": run_filter,
            "summary_for_run": summary_for_run,
            "records_for_run": records_for_run,
            "limit_jobs": limit_jobs,
            "limit_attempts": limit_attempts,
        }
    )
    return templates.TemplateResponse(request, "operator/delivery.html", context)


@OPERATOR_UI_ROUTER.api_route(
    "/operator/explain-audit",
    methods=["GET", "POST"],
    response_class=HTMLResponse,
)
def operator_explain_audit_page(
    request: Request,
    run_id: str = Form(default=""),
    customer_id: str = Form(default=""),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    errors: list[str] = []
    notice: str | None = None
    decision: dict[str, Any] | None = None

    lookup_run_id = _parse_optional_form_value(run_id)
    lookup_customer_id = _parse_optional_form_value(customer_id)
    if request.method == "POST":
        if not lookup_run_id or not lookup_customer_id:
            errors.append("Provide both run_id and customer_id for explain lookup.")
        else:
            try:
                UUID(lookup_run_id)
                decision = fetch_policy_decision_audit(
                    run_id=lookup_run_id,
                    customer_id=lookup_customer_id,
                )
                if decision is None:
                    notice = (
                        "No policy decision row found for the requested run/customer."
                    )
            except ValueError:
                errors.append(
                    f"Invalid run_id format (expected UUID): {lookup_run_id}"
                )
            except Exception as exc:
                errors.append(f"policy decision lookup failed: {exc}")

    try:
        lifecycle_actions = lifecycle_service.list_lifecycle_audit(limit=20)
    except Exception as exc:
        lifecycle_actions = []
        errors.append(f"lifecycle audit unavailable: {exc}")

    try:
        delivery_attempts = delivery_runner.list_recent_delivery_attempts(limit=20)
    except Exception as exc:
        delivery_attempts = []
        errors.append(f"delivery audit unavailable: {exc}")

    context = _base_context(
        request=request,
        principal=principal,
        page_title="Explain / Audit",
        active_nav="/operator/explain-audit",
        notice=notice,
        error_message="\n".join(errors) if errors else None,
    )
    context.update(
        {
            "lookup_run_id": lookup_run_id or "",
            "lookup_customer_id": lookup_customer_id or "",
            "decision": decision,
            "lifecycle_actions": lifecycle_actions,
            "delivery_attempts": delivery_attempts,
        }
    )
    return templates.TemplateResponse(request, "operator/explain_audit.html", context)


@OPERATOR_UI_ROUTER.get("/operator/readiness", response_class=HTMLResponse)
def operator_readiness_page(request: Request) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    payload, errors = _collect_model_and_readiness()

    context = _base_context(
        request=request,
        principal=principal,
        page_title="Integrations / Readiness",
        active_nav="/operator/readiness",
        error_message="\n".join(errors) if errors else None,
    )
    context.update(payload)
    return templates.TemplateResponse(request, "operator/readiness.html", context)
