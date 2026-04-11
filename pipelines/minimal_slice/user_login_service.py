from __future__ import annotations

from dataclasses import dataclass

from .access_roles import ROLE_PRECEDENCE, parse_role
from .password_hashing import hash_password, password_hash_needs_rehash, verify_password
from .user_admin_audit_repository import PostgresUserAdminAuditRepository
from .user_admin_repository import PostgresUserAdminRepository
from .user_credentials_repository import PostgresUserCredentialsRepository


def _normalize_username(username: str) -> str:
    normalized = (username or "").strip().lower()
    if not normalized:
        raise ValueError("username is required.")
    return normalized


def _primary_role(roles: tuple[str, ...]) -> str:
    for role in ROLE_PRECEDENCE:
        if role.value in roles:
            return role.value
    raise ValueError("User has no supported roles assigned.")


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    username: str
    roles: tuple[str, ...]
    primary_role: str


@dataclass(frozen=True)
class LoginResult:
    user: AuthenticatedUser
    require_password_reset: bool


class UserLoginService:
    def __init__(
        self,
        *,
        user_repository: PostgresUserAdminRepository | None = None,
        credentials_repository: PostgresUserCredentialsRepository | None = None,
        audit_repository: PostgresUserAdminAuditRepository | None = None,
    ) -> None:
        self._users = user_repository or PostgresUserAdminRepository()
        self._credentials = (
            credentials_repository or PostgresUserCredentialsRepository()
        )
        self._audit = audit_repository or PostgresUserAdminAuditRepository()

    def _user_roles(self, user_row: dict[str, object]) -> tuple[str, ...]:
        raw_roles = user_row.get("roles")
        if not isinstance(raw_roles, (list, tuple)):
            return ()
        parsed: list[str] = []
        for role in raw_roles:
            try:
                parsed.append(parse_role(str(role)).value)
            except ValueError:
                continue
        deduped: list[str] = []
        for role in ROLE_PRECEDENCE:
            if role.value in parsed:
                deduped.append(role.value)
        return tuple(deduped)

    def resolve_authenticated_user(self, *, user_id: str) -> AuthenticatedUser | None:
        user = self._users.get_user_by_id(user_id=user_id)
        if user is None or not bool(user.get("is_active")):
            return None
        roles = self._user_roles(user)
        if not roles:
            return None
        return AuthenticatedUser(
            user_id=str(user["user_id"]),
            username=str(user["username"]),
            roles=roles,
            primary_role=_primary_role(roles),
        )

    def credential_status(self, *, user_id: str) -> dict[str, object]:
        user = self._users.get_user_by_id(user_id=user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        credential = self._credentials.get_credentials_by_user_id(user_id=user_id)
        return {
            "has_credentials": credential is not None,
            "require_password_reset": bool(
                credential.get("require_password_reset") if credential else False
            ),
            "password_updated_at": credential.get("password_updated_at")
            if credential
            else None,
        }

    def set_password(
        self,
        *,
        user_id: str,
        new_password: str,
        actor_id: str,
        require_password_reset: bool = False,
        audit_action: str = "password_set",
    ) -> dict[str, object]:
        user = self._users.get_user_by_id(user_id=user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")

        hashed = hash_password(new_password)
        credential = self._credentials.upsert_password_hash(
            user_id=user_id,
            password_hash=hashed,
            password_updated_by=actor_id,
            require_password_reset=require_password_reset,
        )
        self._audit.append_audit_entry(
            audit_action=audit_action,
            actor_id=actor_id,
            target_user_id=user_id,
            details={
                "require_password_reset": require_password_reset,
                "password_hash_scheme": "argon2",
            },
        )
        return {
            "user_id": user_id,
            "has_credentials": True,
            "require_password_reset": bool(credential["require_password_reset"]),
            "password_updated_at": credential["password_updated_at"],
        }

    def reset_password(
        self,
        *,
        user_id: str,
        temporary_password: str,
        actor_id: str,
    ) -> dict[str, object]:
        return self.set_password(
            user_id=user_id,
            new_password=temporary_password,
            actor_id=actor_id,
            require_password_reset=True,
            audit_action="password_reset",
        )

    def verify_login(self, *, username: str, password: str) -> LoginResult | None:
        normalized_username = _normalize_username(username)
        user = self._users.get_user_by_username(username=normalized_username)
        if user is None or not bool(user.get("is_active")):
            return None

        roles = self._user_roles(user)
        if not roles:
            return None

        credential = self._credentials.get_credentials_by_user_id(
            user_id=str(user["user_id"])
        )
        if credential is None:
            return None
        if not verify_password(password, str(credential["password_hash"])):
            return None

        if password_hash_needs_rehash(str(credential["password_hash"])):
            self._credentials.upsert_password_hash(
                user_id=str(user["user_id"]),
                password_hash=hash_password(password),
                password_updated_by="system:rehash",
                require_password_reset=bool(credential["require_password_reset"]),
            )

        user_identity = AuthenticatedUser(
            user_id=str(user["user_id"]),
            username=str(user["username"]),
            roles=roles,
            primary_role=_primary_role(roles),
        )
        return LoginResult(
            user=user_identity,
            require_password_reset=bool(credential["require_password_reset"]),
        )
