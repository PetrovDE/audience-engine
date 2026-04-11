from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pipelines.minimal_slice import user_admin
from pipelines.minimal_slice.access_roles import ROLE_LABELS, ROLE_VALUES
from services.retrieval_api.operator_ui import (
    NAV_ITEMS,
    OPERATOR_UI_ROUTER,
    _base_context,
    _require_signed_in_admin,
    templates,
)

_USER_ADMIN_PATH = "/operator/admin/users"

if not any(item.get("path") == _USER_ADMIN_PATH for item in NAV_ITEMS):
    NAV_ITEMS.append({"path": _USER_ADMIN_PATH, "label": "User Admin"})


def _optional_form_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _render_users_page(
    *,
    request: Request,
    principal: Any,
    notice: str | None = None,
    error_message: str | None = None,
    status_code: int = 200,
) -> Response:
    users = user_admin.list_users(include_inactive=True)
    context = _base_context(
        request=request,
        principal=principal,
        page_title="User Administration",
        active_nav=_USER_ADMIN_PATH,
        notice=notice,
        error_message=error_message,
    )
    context.update(
        {
            "users": users,
            "role_values": ROLE_VALUES,
            "role_labels": ROLE_LABELS,
        }
    )
    return templates.TemplateResponse(
        request,
        "operator/users.html",
        context,
        status_code=status_code,
    )


def _render_user_detail_page(
    *,
    request: Request,
    principal: Any,
    user_id: str,
    notice: str | None = None,
    error_message: str | None = None,
    status_code: int = 200,
) -> Response:
    user = user_admin.get_user(user_id=user_id)
    if user is None:
        return _render_users_page(
            request=request,
            principal=principal,
            error_message=f"User not found: {user_id}",
            status_code=404,
        )

    audit_rows = user_admin.list_audit_entries(target_user_id=user_id, limit=50)
    context = _base_context(
        request=request,
        principal=principal,
        page_title=f"User: {user['username']}",
        active_nav=_USER_ADMIN_PATH,
        notice=notice,
        error_message=error_message,
    )
    context.update(
        {
            "user_row": user,
            "audit_rows": audit_rows,
            "role_values": ROLE_VALUES,
            "role_labels": ROLE_LABELS,
        }
    )
    return templates.TemplateResponse(
        request,
        "operator/user_detail.html",
        context,
        status_code=status_code,
    )


@OPERATOR_UI_ROUTER.get(_USER_ADMIN_PATH, response_class=HTMLResponse)
def operator_user_admin_list_page(
    request: Request,
    notice: str | None = Query(default=None),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    return _render_users_page(request=request, principal=principal, notice=notice)


@OPERATOR_UI_ROUTER.post(_USER_ADMIN_PATH, response_class=HTMLResponse)
def operator_user_admin_create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(default=""),
    email: str = Form(default=""),
    roles: list[str] = Form(default=[]),
    is_active: str = Form(default="1"),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal

    try:
        created = user_admin.create_user(
            username=username,
            display_name=_optional_form_value(display_name),
            email=_optional_form_value(email),
            initial_roles=roles,
            is_active=is_active == "1",
            actor_id=principal.actor_id,
        )
    except ValueError as exc:
        return _render_users_page(
            request=request,
            principal=principal,
            error_message=str(exc),
            status_code=400,
        )

    notice = quote_plus(f"User created: {created['username']}")
    return RedirectResponse(
        url=f"{_USER_ADMIN_PATH}/{created['user_id']}?notice={notice}",
        status_code=303,
    )


@OPERATOR_UI_ROUTER.get(f"{_USER_ADMIN_PATH}/{{user_id}}", response_class=HTMLResponse)
def operator_user_admin_detail_page(
    request: Request,
    user_id: str,
    notice: str | None = Query(default=None),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    return _render_user_detail_page(
        request=request,
        principal=principal,
        user_id=user_id,
        notice=notice,
    )


@OPERATOR_UI_ROUTER.post(
    f"{_USER_ADMIN_PATH}/{{user_id}}/profile",
    response_class=HTMLResponse,
)
def operator_user_admin_update_profile(
    request: Request,
    user_id: str,
    display_name: str = Form(default=""),
    email: str = Form(default=""),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    try:
        user_admin.update_user_profile(
            user_id=user_id,
            display_name=_optional_form_value(display_name),
            email=_optional_form_value(email),
            actor_id=principal.actor_id,
        )
    except ValueError as exc:
        return _render_user_detail_page(
            request=request,
            principal=principal,
            user_id=user_id,
            error_message=str(exc),
            status_code=400,
        )
    notice = quote_plus("User profile updated.")
    return RedirectResponse(
        url=f"{_USER_ADMIN_PATH}/{user_id}?notice={notice}",
        status_code=303,
    )


@OPERATOR_UI_ROUTER.post(
    f"{_USER_ADMIN_PATH}/{{user_id}}/activate",
    response_class=HTMLResponse,
)
def operator_user_admin_activate(request: Request, user_id: str) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    try:
        user_admin.set_user_active(
            user_id=user_id,
            is_active=True,
            actor_id=principal.actor_id,
        )
    except ValueError as exc:
        return _render_user_detail_page(
            request=request,
            principal=principal,
            user_id=user_id,
            error_message=str(exc),
            status_code=400,
        )
    notice = quote_plus("User activated.")
    return RedirectResponse(
        url=f"{_USER_ADMIN_PATH}/{user_id}?notice={notice}",
        status_code=303,
    )


@OPERATOR_UI_ROUTER.post(
    f"{_USER_ADMIN_PATH}/{{user_id}}/deactivate",
    response_class=HTMLResponse,
)
def operator_user_admin_deactivate(request: Request, user_id: str) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    try:
        user_admin.set_user_active(
            user_id=user_id,
            is_active=False,
            actor_id=principal.actor_id,
        )
    except ValueError as exc:
        return _render_user_detail_page(
            request=request,
            principal=principal,
            user_id=user_id,
            error_message=str(exc),
            status_code=400,
        )
    notice = quote_plus("User deactivated.")
    return RedirectResponse(
        url=f"{_USER_ADMIN_PATH}/{user_id}?notice={notice}",
        status_code=303,
    )


@OPERATOR_UI_ROUTER.post(
    f"{_USER_ADMIN_PATH}/{{user_id}}/roles/assign",
    response_class=HTMLResponse,
)
def operator_user_admin_assign_role(
    request: Request,
    user_id: str,
    role: str = Form(...),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    try:
        user_admin.assign_role(
            user_id=user_id,
            role=role,
            actor_id=principal.actor_id,
        )
    except ValueError as exc:
        return _render_user_detail_page(
            request=request,
            principal=principal,
            user_id=user_id,
            error_message=str(exc),
            status_code=400,
        )
    notice = quote_plus(f"Role assigned: {role}")
    return RedirectResponse(
        url=f"{_USER_ADMIN_PATH}/{user_id}?notice={notice}",
        status_code=303,
    )


@OPERATOR_UI_ROUTER.post(
    f"{_USER_ADMIN_PATH}/{{user_id}}/roles/remove",
    response_class=HTMLResponse,
)
def operator_user_admin_remove_role(
    request: Request,
    user_id: str,
    role: str = Form(...),
) -> Response:
    principal = _require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    try:
        user_admin.remove_role(
            user_id=user_id,
            role=role,
            actor_id=principal.actor_id,
        )
    except ValueError as exc:
        return _render_user_detail_page(
            request=request,
            principal=principal,
            user_id=user_id,
            error_message=str(exc),
            status_code=400,
        )
    notice = quote_plus(f"Role removed: {role}")
    return RedirectResponse(
        url=f"{_USER_ADMIN_PATH}/{user_id}?notice={notice}",
        status_code=303,
    )

