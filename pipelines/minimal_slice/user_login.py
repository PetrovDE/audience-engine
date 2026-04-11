from __future__ import annotations

from typing import Any

from .user_login_service import AuthenticatedUser, LoginResult, UserLoginService

_service = UserLoginService()


def verify_login(*, username: str, password: str) -> LoginResult | None:
    return _service.verify_login(username=username, password=password)


def resolve_authenticated_user(*, user_id: str) -> AuthenticatedUser | None:
    return _service.resolve_authenticated_user(user_id=user_id)


def set_password(
    *,
    user_id: str,
    new_password: str,
    actor_id: str,
    require_password_reset: bool = False,
) -> dict[str, Any]:
    return _service.set_password(
        user_id=user_id,
        new_password=new_password,
        actor_id=actor_id,
        require_password_reset=require_password_reset,
    )


def reset_password(
    *,
    user_id: str,
    temporary_password: str,
    actor_id: str,
) -> dict[str, Any]:
    return _service.reset_password(
        user_id=user_id,
        temporary_password=temporary_password,
        actor_id=actor_id,
    )


def credential_status(*, user_id: str) -> dict[str, object]:
    return _service.credential_status(user_id=user_id)

