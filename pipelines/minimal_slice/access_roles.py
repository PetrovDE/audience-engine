from __future__ import annotations

from enum import Enum
from typing import Iterable


class AccessRole(str, Enum):
    ADMIN_OPERATOR = "admin_operator"
    DATA_ENGINEER = "data_engineer"
    ML_ANALYST = "ml_analyst"
    CAMPAIGN_USER = "campaign_user"


ROLE_VALUES = tuple(role.value for role in AccessRole)
ROLE_PRECEDENCE = (
    AccessRole.ADMIN_OPERATOR,
    AccessRole.DATA_ENGINEER,
    AccessRole.ML_ANALYST,
    AccessRole.CAMPAIGN_USER,
)
ROLE_LABELS: dict[str, str] = {
    AccessRole.ADMIN_OPERATOR.value: "Admin Operator",
    AccessRole.DATA_ENGINEER.value: "Data Engineer",
    AccessRole.ML_ANALYST.value: "ML Analyst",
    AccessRole.CAMPAIGN_USER.value: "Campaign User",
}


def normalize_role_value(role_value: str) -> str:
    normalized = role_value.strip().lower()
    if not normalized:
        raise ValueError("role is required.")
    return normalized


def validate_role_value(role_value: str) -> str:
    normalized = normalize_role_value(role_value)
    if normalized not in ROLE_VALUES:
        allowed = ", ".join(ROLE_VALUES)
        raise ValueError(f"Invalid role '{role_value}'. Allowed roles: {allowed}.")
    return normalized


def validate_role_values(role_values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw_role in role_values:
        normalized = validate_role_value(raw_role)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return tuple(deduped)


def parse_role(role_value: str) -> AccessRole:
    return AccessRole(validate_role_value(role_value))

