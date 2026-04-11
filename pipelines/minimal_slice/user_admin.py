from __future__ import annotations

import argparse
import json
import os
from typing import Any

from . import user_login
from .user_admin_service import UserAdminService

_service = UserAdminService()

BOOTSTRAP_ADMIN_USERNAME_ENV = "AE_BOOTSTRAP_ADMIN_USERNAME"
BOOTSTRAP_ADMIN_DISPLAY_NAME_ENV = "AE_BOOTSTRAP_ADMIN_DISPLAY_NAME"
BOOTSTRAP_ADMIN_EMAIL_ENV = "AE_BOOTSTRAP_ADMIN_EMAIL"
BOOTSTRAP_ADMIN_PASSWORD_ENV = "AE_BOOTSTRAP_ADMIN_PASSWORD"


def create_user(
    *,
    username: str,
    display_name: str | None = None,
    email: str | None = None,
    initial_roles: list[str] | tuple[str, ...] = (),
    is_active: bool = True,
    actor_id: str = "system:user_admin",
) -> dict[str, Any]:
    return _service.create_user(
        username=username,
        display_name=display_name,
        email=email,
        initial_roles=initial_roles,
        is_active=is_active,
        actor_id=actor_id,
    )


def list_users(*, include_inactive: bool = True) -> list[dict[str, Any]]:
    return _service.list_users(include_inactive=include_inactive)


def get_user(*, user_id: str) -> dict[str, Any] | None:
    return _service.get_user(user_id=user_id)


def update_user_profile(
    *,
    user_id: str,
    display_name: str | None = None,
    email: str | None = None,
    actor_id: str = "system:user_admin",
) -> dict[str, Any]:
    return _service.update_user_profile(
        user_id=user_id,
        display_name=display_name,
        email=email,
        actor_id=actor_id,
    )


def set_user_active(
    *,
    user_id: str,
    is_active: bool,
    actor_id: str = "system:user_admin",
) -> dict[str, Any]:
    return _service.set_user_active(
        user_id=user_id,
        is_active=is_active,
        actor_id=actor_id,
    )


def assign_role(
    *,
    user_id: str,
    role: str,
    actor_id: str = "system:user_admin",
) -> tuple[str, ...]:
    return _service.assign_role(user_id=user_id, role=role, actor_id=actor_id)


def remove_role(
    *,
    user_id: str,
    role: str,
    actor_id: str = "system:user_admin",
) -> tuple[str, ...]:
    return _service.remove_role(user_id=user_id, role=role, actor_id=actor_id)


def get_effective_roles(*, user_id: str) -> tuple[str, ...]:
    return _service.get_effective_roles(user_id=user_id)


def list_audit_entries(
    *,
    target_user_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _service.list_audit_entries(target_user_id=target_user_id, limit=limit)


def bootstrap_dev_admin_user(
    *,
    dry_run: bool = False,
    username: str | None = None,
    display_name: str | None = None,
    email: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    resolved_username = (
        username or os.getenv(BOOTSTRAP_ADMIN_USERNAME_ENV, "admin")
    ).strip()
    resolved_display_name = (
        display_name
        if display_name is not None
        else os.getenv(BOOTSTRAP_ADMIN_DISPLAY_NAME_ENV, "Admin Operator").strip()
    )
    resolved_email = (
        email
        if email is not None
        else os.getenv(BOOTSTRAP_ADMIN_EMAIL_ENV, "admin@example.com").strip()
    )
    resolved_password = (
        password
        if password is not None
        else os.getenv(
            BOOTSTRAP_ADMIN_PASSWORD_ENV,
            os.getenv("OPERATOR_UI_PASSWORD", ""),
        ).strip()
    )
    payload: dict[str, Any] = {
        "bootstrap": "user_admin_dev_admin",
        "mode": "dry_run" if dry_run else "apply",
        "username": resolved_username,
        "display_name": resolved_display_name,
        "email": resolved_email,
        "required_roles": ["admin_operator"],
        "password_seeded": bool(resolved_password),
    }
    if dry_run:
        return payload
    result = _service.ensure_bootstrap_admin_user(
        username=resolved_username,
        display_name=resolved_display_name,
        email=resolved_email,
        actor_id="system:bootstrap",
    )
    payload["result"] = result
    if resolved_password:
        user_login.set_password(
            user_id=str(result["user_id"]),
            new_password=resolved_password,
            actor_id="system:bootstrap",
            require_password_reset=False,
        )
    return payload


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="User/role admin bootstrap helper for local/dev internal testing."
    )
    parser.add_argument(
        "--bootstrap-dev-admin",
        action="store_true",
        help="Create or reconcile one active admin_operator user for local/dev.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show resolved bootstrap values without writing to Postgres.",
    )
    parser.add_argument("--username", default=None, help="Override bootstrap username.")
    parser.add_argument(
        "--display-name",
        default=None,
        help="Override bootstrap display name.",
    )
    parser.add_argument("--email", default=None, help="Override bootstrap email.")
    parser.add_argument(
        "--password",
        default=None,
        help="Override bootstrap password (not printed in output).",
    )
    args = parser.parse_args()

    if not args.bootstrap_dev_admin:
        parser.error("No action selected. Use --bootstrap-dev-admin.")

    result = bootstrap_dev_admin_user(
        dry_run=bool(args.dry_run),
        username=args.username,
        display_name=args.display_name,
        email=args.email,
        password=args.password,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()


__all__ = [
    "create_user",
    "list_users",
    "get_user",
    "update_user_profile",
    "set_user_active",
    "assign_role",
    "remove_role",
    "get_effective_roles",
    "list_audit_entries",
    "bootstrap_dev_admin_user",
]
