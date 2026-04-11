from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pipelines.minimal_slice import user_admin, user_login
from services.retrieval_api import operator_ui

_USER_ADMIN_PATH = "/operator/admin/users"


def _render_credentials_page(
    *,
    request: Request,
    principal,
    user_id: str,
    notice: str | None = None,
    error_message: str | None = None,
    status_code: int = 200,
) -> Response:
    user = user_admin.get_user(user_id=user_id)
    if user is None:
        message = quote_plus(f"User not found: {user_id}")
        return RedirectResponse(
            url=f"{_USER_ADMIN_PATH}?notice={message}",
            status_code=303,
        )
    credential = user_login.credential_status(user_id=user_id)
    context = operator_ui._base_context(
        request=request,
        principal=principal,
        page_title=f"Credentials: {user['username']}",
        active_nav=_USER_ADMIN_PATH,
        notice=notice,
        error_message=error_message,
    )
    context.update({"user_row": user, "credential": credential})
    return operator_ui.templates.TemplateResponse(
        request,
        "operator/user_credentials.html",
        context,
        status_code=status_code,
    )


@operator_ui.OPERATOR_UI_ROUTER.get(
    "/operator/admin/users/{user_id}/credentials",
    response_class=HTMLResponse,
)
def operator_user_credentials_page(
    request: Request,
    user_id: str,
    notice: str | None = Query(default=None),
) -> Response:
    principal = operator_ui._require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    return _render_credentials_page(
        request=request,
        principal=principal,
        user_id=user_id,
        notice=notice,
    )


@operator_ui.OPERATOR_UI_ROUTER.post(
    "/operator/admin/users/{user_id}/credentials/set-password",
    response_class=HTMLResponse,
)
def operator_user_credentials_set_password(
    request: Request,
    user_id: str,
    new_password: str = Form(...),
    require_password_reset: str = Form(default="0"),
) -> Response:
    principal = operator_ui._require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    try:
        user_login.set_password(
            user_id=user_id,
            new_password=new_password,
            actor_id=principal.actor_id,
            require_password_reset=require_password_reset == "1",
        )
    except ValueError as exc:
        return _render_credentials_page(
            request=request,
            principal=principal,
            user_id=user_id,
            error_message=str(exc),
            status_code=400,
        )
    notice = quote_plus("Password set.")
    return RedirectResponse(
        url=f"/operator/admin/users/{user_id}/credentials?notice={notice}",
        status_code=303,
    )


@operator_ui.OPERATOR_UI_ROUTER.post(
    "/operator/admin/users/{user_id}/credentials/reset-password",
    response_class=HTMLResponse,
)
def operator_user_credentials_reset_password(
    request: Request,
    user_id: str,
    temporary_password: str = Form(...),
) -> Response:
    principal = operator_ui._require_signed_in_admin(request)
    if isinstance(principal, RedirectResponse):
        return principal
    try:
        user_login.reset_password(
            user_id=user_id,
            temporary_password=temporary_password,
            actor_id=principal.actor_id,
        )
    except ValueError as exc:
        return _render_credentials_page(
            request=request,
            principal=principal,
            user_id=user_id,
            error_message=str(exc),
            status_code=400,
        )
    notice = quote_plus("Temporary password reset complete.")
    return RedirectResponse(
        url=f"/operator/admin/users/{user_id}/credentials?notice={notice}",
        status_code=303,
    )
