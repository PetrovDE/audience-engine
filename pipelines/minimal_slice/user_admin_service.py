from __future__ import annotations

import re
from typing import Any

from .access_roles import (
    ROLE_VALUES,
    AccessRole,
    validate_role_value,
    validate_role_values,
)
from .user_admin_audit_repository import PostgresUserAdminAuditRepository
from .user_admin_repository import PostgresUserAdminRepository

_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def _normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not normalized:
        raise ValueError("username is required.")
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "username must be 3-64 chars using lowercase letters, "
            "digits, '.', '-' or '_'."
        )
    return normalized


def _normalize_display_name(display_name: str | None, *, username: str) -> str:
    candidate = (display_name or "").strip()
    return candidate if candidate else username


def _normalize_optional_email(email: str | None) -> str | None:
    if email is None:
        return None
    cleaned = email.strip()
    return cleaned if cleaned else None


class UserAdminService:
    def __init__(
        self,
        *,
        repository: PostgresUserAdminRepository | None = None,
        audit_repository: PostgresUserAdminAuditRepository | None = None,
    ) -> None:
        self._repository = repository or PostgresUserAdminRepository()
        if audit_repository is not None:
            self._audit_repository = audit_repository
        elif (
            hasattr(self._repository, "append_audit_entry")
            and hasattr(self._repository, "list_audit_entries")
        ):
            self._audit_repository = self._repository
        else:
            self._audit_repository = PostgresUserAdminAuditRepository()

    def supported_roles(self) -> tuple[str, ...]:
        return ROLE_VALUES

    def _append_audit_entry(
        self,
        *,
        audit_action: str,
        actor_id: str,
        target_user_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit_repository.append_audit_entry(
            audit_action=audit_action,
            actor_id=actor_id,
            target_user_id=target_user_id,
            details=details,
        )

    def _require_user(self, *, user_id: str) -> dict[str, Any]:
        user = self._repository.get_user_by_id(user_id=user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        return user

    def get_user(self, *, user_id: str) -> dict[str, Any] | None:
        return self._repository.get_user_by_id(user_id=user_id)

    def list_users(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        return self._repository.list_users(include_inactive=include_inactive)

    def get_effective_roles(self, *, user_id: str) -> tuple[str, ...]:
        self._require_user(user_id=user_id)
        return self._repository.list_user_roles(user_id=user_id)

    def create_user(
        self,
        *,
        username: str,
        display_name: str | None,
        email: str | None,
        initial_roles: list[str] | tuple[str, ...],
        is_active: bool,
        actor_id: str,
    ) -> dict[str, Any]:
        resolved_username = _normalize_username(username)
        if (
            self._repository.get_user_by_username(username=resolved_username)
            is not None
        ):
            raise ValueError(f"username already exists: {resolved_username}")

        user = self._repository.create_user(
            username=resolved_username,
            display_name=_normalize_display_name(
                display_name,
                username=resolved_username,
            ),
            email=_normalize_optional_email(email),
            is_active=is_active,
            actor_id=actor_id,
        )

        resolved_roles = validate_role_values(initial_roles)
        for role in resolved_roles:
            self._repository.assign_role(
                user_id=str(user["user_id"]),
                role=role,
                actor_id=actor_id,
            )

        self._append_audit_entry(
            audit_action="user_created",
            actor_id=actor_id,
            target_user_id=str(user["user_id"]),
            details={
                "username": user["username"],
                "roles": list(resolved_roles),
                "is_active": bool(user["is_active"]),
            },
        )
        return self._require_user(user_id=str(user["user_id"]))

    def update_user_profile(
        self,
        *,
        user_id: str,
        display_name: str | None,
        email: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        if display_name is None and email is None:
            raise ValueError("Provide display_name and/or email.")

        resolved_display_name = None
        if display_name is not None:
            resolved_display_name = display_name.strip()
            if not resolved_display_name:
                raise ValueError("display_name cannot be empty when provided.")
        updated = self._repository.update_user_profile(
            user_id=user_id,
            display_name=resolved_display_name,
            email=_normalize_optional_email(email) if email is not None else None,
            actor_id=actor_id,
        )
        if updated is None:
            raise ValueError(f"User not found: {user_id}")
        self._append_audit_entry(
            audit_action="user_profile_updated",
            actor_id=actor_id,
            target_user_id=user_id,
            details={
                "display_name": updated["display_name"],
                "email": updated["email"],
            },
        )
        return updated

    def set_user_active(
        self,
        *,
        user_id: str,
        is_active: bool,
        actor_id: str,
    ) -> dict[str, Any]:
        updated = self._repository.set_user_active(
            user_id=user_id,
            is_active=is_active,
            actor_id=actor_id,
        )
        if updated is None:
            raise ValueError(f"User not found: {user_id}")
        self._append_audit_entry(
            audit_action="user_activated" if is_active else "user_deactivated",
            actor_id=actor_id,
            target_user_id=user_id,
            details={"is_active": is_active},
        )
        return updated

    def assign_role(
        self,
        *,
        user_id: str,
        role: str,
        actor_id: str,
    ) -> tuple[str, ...]:
        resolved_role = validate_role_value(role)
        self._require_user(user_id=user_id)
        changed = self._repository.assign_role(
            user_id=user_id,
            role=resolved_role,
            actor_id=actor_id,
        )
        effective_roles = self._repository.list_user_roles(user_id=user_id)
        self._append_audit_entry(
            audit_action="role_assigned",
            actor_id=actor_id,
            target_user_id=user_id,
            details={
                "role": resolved_role,
                "changed": changed,
                "effective_roles": list(effective_roles),
            },
        )
        return effective_roles

    def remove_role(
        self,
        *,
        user_id: str,
        role: str,
        actor_id: str,
    ) -> tuple[str, ...]:
        resolved_role = validate_role_value(role)
        self._require_user(user_id=user_id)
        changed = self._repository.remove_role(
            user_id=user_id,
            role=resolved_role,
            actor_id=actor_id,
        )
        effective_roles = self._repository.list_user_roles(user_id=user_id)
        self._append_audit_entry(
            audit_action="role_removed",
            actor_id=actor_id,
            target_user_id=user_id,
            details={
                "role": resolved_role,
                "changed": changed,
                "effective_roles": list(effective_roles),
            },
        )
        return effective_roles

    def list_audit_entries(
        self,
        *,
        target_user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._audit_repository.list_audit_entries(
            target_user_id=target_user_id,
            limit=limit,
        )

    def ensure_bootstrap_admin_user(
        self,
        *,
        username: str,
        display_name: str | None,
        email: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        resolved_username = _normalize_username(username)
        user = self._repository.get_user_by_username(username=resolved_username)
        created = False
        if user is None:
            user = self.create_user(
                username=resolved_username,
                display_name=display_name,
                email=email,
                initial_roles=[AccessRole.ADMIN_OPERATOR.value],
                is_active=True,
                actor_id=actor_id,
            )
            created = True

        user_id = str(user["user_id"])
        roles = self._repository.list_user_roles(user_id=user_id)
        if AccessRole.ADMIN_OPERATOR.value not in roles:
            roles = self.assign_role(
                user_id=user_id,
                role=AccessRole.ADMIN_OPERATOR.value,
                actor_id=actor_id,
            )

        if not bool(user["is_active"]):
            user = self.set_user_active(
                user_id=user_id,
                is_active=True,
                actor_id=actor_id,
            )
        else:
            user = self._require_user(user_id=user_id)

        self._append_audit_entry(
            audit_action="bootstrap_admin_verified",
            actor_id=actor_id,
            target_user_id=user_id,
            details={
                "created": created,
                "username": user["username"],
                "roles": list(roles),
            },
        )
        return {
            "created": created,
            "user_id": user_id,
            "username": user["username"],
            "is_active": bool(user["is_active"]),
            "roles": list(self._repository.list_user_roles(user_id=user_id)),
        }
