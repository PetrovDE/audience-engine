from __future__ import annotations

import hmac
from urllib.parse import quote

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.routing import APIRoute

from pipelines.minimal_slice import user_login
from services.retrieval_api.auth import Principal, Role
from services.retrieval_api.operator_i18n import (
    apply_template_context,
    current_path_with_query,
    localize_access_message,
    set_language_cookie,
    translate_for_request,
)
from services.retrieval_api.operator_session_auth import (
    issue_session_cookie_value,
    resolve_session_subject,
    session_signing_is_configured,
)

from . import (
    operator_control_plane_management,
    operator_control_plane_ui,
    operator_ui,
    operator_user_admin_ui,
)
from .operator_access import (
    evaluate_access,
    filtered_nav_items,
    show_control_plane_nav_fallback,
    visible_guidance_roles,
)


def _drop_legacy_login_routes() -> None:
    retained = []
    for route in operator_ui.OPERATOR_UI_ROUTER.routes:
        if not isinstance(route, APIRoute):
            retained.append(route)
            continue
        methods = set(route.methods or set())
        is_login = route.path == "/operator/login" and bool(methods & {"GET", "POST"})
        is_logout = route.path == "/operator/logout" and "POST" in methods
        if is_login or is_logout:
            continue
        retained.append(route)
    operator_ui.OPERATOR_UI_ROUTER.routes[:] = retained


def _env_bootstrap_credentials() -> tuple[str, str] | None:
    return operator_ui._load_operator_ui_credentials()


def _env_bootstrap_principal(username: str) -> Principal | None:
    configured = _env_bootstrap_credentials()
    if configured is None:
        return None
    expected_username, _expected_password = configured
    if not hmac.compare_digest(username.strip(), expected_username):
        return None
    return Principal(
        role=Role.ADMIN_OPERATOR,
        roles=(Role.ADMIN_OPERATOR,),
        actor_id=f"operator_ui_env:{expected_username}",
    )


def _principal_from_persisted_identity(user_id: str) -> Principal | None:
    try:
        identity = user_login.resolve_authenticated_user(user_id=user_id)
    except Exception:
        return None
    if identity is None:
        return None
    try:
        roles = tuple(Role(role) for role in identity.roles)
        primary = Role(identity.primary_role)
    except ValueError:
        return None
    return Principal(
        role=primary,
        roles=roles,
        user_id=identity.user_id,
        actor_id=f"operator_user:{identity.username}",
    )


def _signed_in_principal(request: Request) -> Principal | None:
    subject = resolve_session_subject(
        request.cookies.get(operator_ui.OPERATOR_SESSION_COOKIE)
    )
    if subject is None:
        return None
    if subject.subject_type == "user":
        return _principal_from_persisted_identity(subject.subject_id)
    if subject.subject_type == "env_admin":
        return _env_bootstrap_principal(subject.subject_id)
    return None


def _redirect_to_login(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    encoded = quote(next_path, safe="/?=&")
    return RedirectResponse(url=f"/operator/login?next={encoded}", status_code=303)


def _redirect_to_forbidden(request: Request, *, message: str) -> RedirectResponse:
    encoded_message = quote(message, safe="")
    encoded_path = quote(request.url.path, safe="/")
    return RedirectResponse(
        url=f"/operator/forbidden?message={encoded_message}&path={encoded_path}",
        status_code=303,
    )


def _require_signed_in_admin(request: Request) -> Principal | RedirectResponse:
    principal = _signed_in_principal(request)
    if principal is None:
        return _redirect_to_login(request)
    decision = evaluate_access(
        roles=principal.roles,
        path=request.url.path,
        method=request.method,
    )
    if not decision.allowed:
        return _redirect_to_forbidden(
            request,
            message=localize_access_message(
                request=request,
                message=str(decision.message or "Access denied for this page."),
            ),
        )
    return principal


def _login_context(
    *,
    request: Request,
    next_path: str,
    error_message: str | None = None,
) -> dict[str, object]:
    context: dict[str, object] = {
        "request": request,
        "next_path": operator_ui._safe_next_path(next_path),
        "language_next_path": current_path_with_query(request),
        "auth_configured": session_signing_is_configured(),
        "error_message": error_message,
    }
    return apply_template_context(request=request, context=context)


def _issue_session_response(
    *,
    request: Request,
    next_path: str,
    subject_type: str,
    subject_id: str,
) -> RedirectResponse:
    response = RedirectResponse(url=next_path, status_code=303)
    response.set_cookie(
        key=operator_ui.OPERATOR_SESSION_COOKIE,
        value=issue_session_cookie_value(
            subject_type=subject_type,
            subject_id=subject_id,
        ),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=8 * 60 * 60,
    )
    return response


_ORIGINAL_BASE_CONTEXT = operator_ui._base_context


def _role_aware_base_context(
    *,
    request: Request,
    principal: Principal | None,
    page_title: str,
    active_nav: str,
    notice: str | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    context = _ORIGINAL_BASE_CONTEXT(
        request=request,
        principal=principal,
        page_title=page_title,
        active_nav=active_nav,
        notice=notice,
        error_message=error_message,
    )
    role_tuple = principal.roles if principal is not None else tuple()
    context["nav_items"] = filtered_nav_items(
        nav_items=list(context.get("nav_items", [])),
        roles=role_tuple,
    )
    context["show_control_plane_nav_fallback"] = show_control_plane_nav_fallback(
        roles=role_tuple
    )
    context["visible_guidance_roles"] = visible_guidance_roles(roles=role_tuple)
    context["language_next_path"] = current_path_with_query(request)
    return apply_template_context(request=request, context=context)


_drop_legacy_login_routes()


@operator_ui.OPERATOR_UI_ROUTER.get("/operator/login", response_class=HTMLResponse)
def operator_login_page(
    request: Request,
    next: str = Query(default=operator_ui.OPERATOR_DASHBOARD_PATH),
) -> Response:
    principal = _signed_in_principal(request)
    safe_next = operator_ui._safe_next_path(next)
    if principal is not None:
        return RedirectResponse(url=safe_next, status_code=303)
    return operator_ui.templates.TemplateResponse(
        request,
        "operator/login.html",
        _login_context(request=request, next_path=safe_next),
    )


@operator_ui.OPERATOR_UI_ROUTER.post("/operator/login", response_class=HTMLResponse)
def operator_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default=operator_ui.OPERATOR_DASHBOARD_PATH),
) -> Response:
    safe_next = operator_ui._safe_next_path(next)
    if not session_signing_is_configured():
        return operator_ui.templates.TemplateResponse(
            request,
            "operator/login.html",
            _login_context(
                request=request,
                next_path=safe_next,
                error_message=translate_for_request(
                    request,
                    "login.error.session_signing_not_configured",
                ),
            ),
            status_code=403,
        )

    login_result = None
    try:
        login_result = user_login.verify_login(
            username=username,
            password=password,
        )
    except Exception:
        login_result = None

    if login_result is not None:
        return _issue_session_response(
            request=request,
            next_path=safe_next,
            subject_type="user",
            subject_id=login_result.user.user_id,
        )

    configured = _env_bootstrap_credentials()
    submitted_username = username.strip()
    if configured is not None:
        expected_username, expected_password = configured
        username_matches = hmac.compare_digest(submitted_username, expected_username)
        password_matches = hmac.compare_digest(password, expected_password)
        if username_matches and password_matches:
            return _issue_session_response(
                request=request,
                next_path=safe_next,
                subject_type="env_admin",
                subject_id=expected_username,
            )

    return operator_ui.templates.TemplateResponse(
        request,
        "operator/login.html",
        _login_context(
            request=request,
            next_path=safe_next,
            error_message=translate_for_request(
                request,
                "login.error.invalid_credentials",
            ),
        ),
        status_code=401,
    )


@operator_ui.OPERATOR_UI_ROUTER.post("/operator/language")
def operator_language_switch(
    language: str = Form(...),
    next: str = Form(default=operator_ui.OPERATOR_DASHBOARD_PATH),
) -> RedirectResponse:
    response = RedirectResponse(
        url=operator_ui._safe_next_path(next),
        status_code=303,
    )
    set_language_cookie(response, language)
    return response


@operator_ui.OPERATOR_UI_ROUTER.post("/operator/logout")
def operator_logout() -> RedirectResponse:
    response = RedirectResponse(url="/operator/login", status_code=303)
    response.delete_cookie(operator_ui.OPERATOR_SESSION_COOKIE)
    return response


@operator_ui.OPERATOR_UI_ROUTER.get("/operator/forbidden", response_class=HTMLResponse)
def operator_forbidden_page(
    request: Request,
    message: str = Query(default=""),
    path: str = Query(default="/operator/dashboard"),
) -> Response:
    principal = _signed_in_principal(request)
    if principal is None:
        return _redirect_to_login(request)
    context = operator_ui._base_context(
        request=request,
        principal=principal,
        page_title=translate_for_request(request, "forbidden.title"),
        active_nav=operator_ui._safe_next_path(path),
        error_message=(
            message
            or translate_for_request(request, "forbidden.default_message")
        ),
    )
    context["denied_path"] = path
    return operator_ui.templates.TemplateResponse(
        request,
        "operator/forbidden.html",
        context,
        status_code=403,
    )


operator_ui._base_context = _role_aware_base_context
operator_control_plane_management._base_context = _role_aware_base_context
operator_user_admin_ui._base_context = _role_aware_base_context
operator_ui._signed_in_principal = _signed_in_principal
operator_ui._require_signed_in_admin = _require_signed_in_admin
operator_control_plane_ui._require_signed_in_admin = _require_signed_in_admin
operator_user_admin_ui._require_signed_in_admin = _require_signed_in_admin
