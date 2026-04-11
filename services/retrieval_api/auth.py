from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, status

from pipelines.minimal_slice.access_roles import ROLE_PRECEDENCE, AccessRole

API_KEY_HEADER = "X-AE-API-Key"

Role = AccessRole

_ROLE_API_KEY_ENV: dict[Role, str] = {
    Role.CAMPAIGN_USER: "AE_CAMPAIGN_API_KEYS",
    Role.ML_ANALYST: "AE_ML_ANALYST_API_KEYS",
    Role.DATA_ENGINEER: "AE_DATA_ENGINEER_API_KEYS",
    Role.ADMIN_OPERATOR: "AE_ADMIN_API_KEYS",
}
_RETRIEVE_ALLOWED_ROLES = frozenset({Role.CAMPAIGN_USER, Role.ADMIN_OPERATOR})


@dataclass(frozen=True)
class Principal:
    role: Role
    actor_id: str
    user_id: str | None = None
    roles: tuple[Role, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        resolved_roles = self.roles if self.roles else (self.role,)
        deduped: list[Role] = []
        for entry in resolved_roles:
            role_value = entry if isinstance(entry, Role) else Role(str(entry))
            if role_value not in deduped:
                deduped.append(role_value)
        if self.role not in deduped:
            deduped.insert(0, self.role)
        object.__setattr__(self, "roles", tuple(deduped))

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def has_any_role(self, roles: set[Role] | frozenset[Role]) -> bool:
        return any(role in self.roles for role in roles)


def _parse_api_keys(raw_value: str | None) -> set[str]:
    if not raw_value:
        return set()
    return {token.strip() for token in raw_value.split(",") if token.strip()}


def _configured_api_keys() -> dict[Role, set[str]]:
    return {
        role: _parse_api_keys(os.getenv(env_var))
        for role, env_var in _ROLE_API_KEY_ENV.items()
    }


def rbac_is_configured() -> bool:
    return any(_configured_api_keys().values())


def _key_fingerprint(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return digest[:12]


def _resolve_principal(api_key: str) -> Principal | None:
    configured = _configured_api_keys()
    matched_roles = [role for role in ROLE_PRECEDENCE if api_key in configured[role]]
    if not matched_roles:
        return None
    primary_role = matched_roles[0]
    return Principal(
        role=primary_role,
        roles=tuple(matched_roles),
        actor_id=f"{primary_role.value}:{_key_fingerprint(api_key)}",
    )


def resolve_principal_from_api_key(api_key: str | None) -> Principal | None:
    if not api_key:
        return None
    return _resolve_principal(api_key)


def resolve_admin_principal_from_api_key(api_key: str | None) -> Principal | None:
    principal = resolve_principal_from_api_key(api_key)
    if principal is None or not principal.has_role(Role.ADMIN_OPERATOR):
        return None
    return principal


def _raise_auth_not_configured() -> None:
    configured_vars = ", ".join(_ROLE_API_KEY_ENV.values())
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "RBAC is not configured. Set one or more of the following env vars: "
            f"{configured_vars}."
        ),
    )


def require_campaign_or_admin(
    x_ae_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> Principal:
    if not rbac_is_configured():
        _raise_auth_not_configured()

    if not x_ae_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing API key header: {API_KEY_HEADER}",
        )

    principal = resolve_principal_from_api_key(x_ae_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key for this endpoint.",
        )
    if not principal.has_any_role(_RETRIEVE_ALLOWED_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Campaign or admin role is required for this endpoint.",
        )
    return principal


def require_admin(
    principal: Principal = Depends(require_campaign_or_admin),
) -> Principal:
    if not principal.has_role(Role.ADMIN_OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin/operator role is required for this endpoint.",
        )
    return principal
