from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum

from fastapi import Depends, Header, HTTPException, status

API_KEY_HEADER = "X-AE-API-Key"


class Role(str, Enum):
    CAMPAIGN_USER = "campaign_user"
    ADMIN_OPERATOR = "admin_operator"


@dataclass(frozen=True)
class Principal:
    role: Role
    actor_id: str


def _parse_api_keys(raw_value: str | None) -> set[str]:
    if not raw_value:
        return set()
    return {token.strip() for token in raw_value.split(",") if token.strip()}


def _configured_api_keys() -> tuple[set[str], set[str]]:
    campaign_keys = _parse_api_keys(os.getenv("AE_CAMPAIGN_API_KEYS"))
    admin_keys = _parse_api_keys(os.getenv("AE_ADMIN_API_KEYS"))
    return campaign_keys, admin_keys


def _key_fingerprint(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return digest[:12]


def _resolve_principal(api_key: str) -> Principal | None:
    campaign_keys, admin_keys = _configured_api_keys()
    if api_key in admin_keys:
        return Principal(
            role=Role.ADMIN_OPERATOR,
            actor_id=f"admin:{_key_fingerprint(api_key)}",
        )
    if api_key in campaign_keys:
        return Principal(
            role=Role.CAMPAIGN_USER,
            actor_id=f"campaign:{_key_fingerprint(api_key)}",
        )
    return None


def _raise_auth_not_configured() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "RBAC is not configured. Set AE_CAMPAIGN_API_KEYS and/or "
            "AE_ADMIN_API_KEYS to enable protected endpoints."
        ),
    )


def require_campaign_or_admin(
    x_ae_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> Principal:
    campaign_keys, admin_keys = _configured_api_keys()
    if not campaign_keys and not admin_keys:
        _raise_auth_not_configured()

    if not x_ae_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing API key header: {API_KEY_HEADER}",
        )

    principal = _resolve_principal(x_ae_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key for this endpoint.",
        )
    return principal


def require_admin(
    principal: Principal = Depends(require_campaign_or_admin),
) -> Principal:
    if principal.role != Role.ADMIN_OPERATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin/operator role is required for this endpoint.",
        )
    return principal
