from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from services.retrieval_api.auth import Role

ROLE_ADMIN = Role.ADMIN_OPERATOR.value
ROLE_DATA_ENGINEER = Role.DATA_ENGINEER.value
ROLE_ML_ANALYST = Role.ML_ANALYST.value
ROLE_CAMPAIGN = Role.CAMPAIGN_USER.value

ALL_BUILT_IN_ROLES = frozenset(
    {ROLE_ADMIN, ROLE_DATA_ENGINEER, ROLE_ML_ANALYST, ROLE_CAMPAIGN}
)
ROLE_GUIDANCE_ORDER: tuple[str, ...] = (
    ROLE_CAMPAIGN,
    ROLE_DATA_ENGINEER,
    ROLE_ML_ANALYST,
    ROLE_ADMIN,
)

NAV_VISIBILITY_MATRIX: dict[str, frozenset[str]] = {
    "/operator/dashboard": ALL_BUILT_IN_ROLES,
    "/operator/defaults": frozenset({ROLE_ADMIN, ROLE_DATA_ENGINEER}),
    "/operator/trigger-run": frozenset(
        {ROLE_ADMIN, ROLE_DATA_ENGINEER, ROLE_CAMPAIGN}
    ),
    "/operator/recent-runs": ALL_BUILT_IN_ROLES,
    "/operator/delivery": ALL_BUILT_IN_ROLES,
    "/operator/explain-audit": ALL_BUILT_IN_ROLES,
    "/operator/readiness": ALL_BUILT_IN_ROLES,
    "/operator/control-plane/versions": frozenset(
        {ROLE_ADMIN, ROLE_DATA_ENGINEER, ROLE_ML_ANALYST}
    ),
    "/operator/admin/users": frozenset({ROLE_ADMIN}),
}

PAGE_ACCESS_MATRIX: dict[str, frozenset[str]] = {
    "operator.dashboard": ALL_BUILT_IN_ROLES,
    "operator.defaults": frozenset({ROLE_ADMIN, ROLE_DATA_ENGINEER}),
    "operator.trigger_run": frozenset({ROLE_ADMIN, ROLE_DATA_ENGINEER, ROLE_CAMPAIGN}),
    "operator.recent_runs": ALL_BUILT_IN_ROLES,
    "operator.delivery": ALL_BUILT_IN_ROLES,
    "operator.explain_audit": ALL_BUILT_IN_ROLES,
    "operator.readiness": ALL_BUILT_IN_ROLES,
    "operator.control_plane_versions": frozenset(
        {ROLE_ADMIN, ROLE_DATA_ENGINEER, ROLE_ML_ANALYST}
    ),
    "operator.user_admin": frozenset({ROLE_ADMIN}),
    "operator.user_credentials_admin": frozenset({ROLE_ADMIN}),
    "operator.forbidden": ALL_BUILT_IN_ROLES,
}

ACTION_ACCESS_MATRIX: dict[str, frozenset[str]] = {
    "operator.defaults.update": frozenset({ROLE_ADMIN, ROLE_DATA_ENGINEER}),
    "operator.trigger_run.submit": frozenset(
        {ROLE_ADMIN, ROLE_DATA_ENGINEER, ROLE_CAMPAIGN}
    ),
    "operator.control_plane.lifecycle.transition": frozenset({ROLE_ADMIN}),
    "operator.control_plane.evidence.record": frozenset({ROLE_ADMIN, ROLE_ML_ANALYST}),
    "operator.user_admin.manage": frozenset({ROLE_ADMIN}),
    "operator.user_credentials.manage": frozenset({ROLE_ADMIN}),
}

_PAGE_PATH_RULES: tuple[tuple[str, str], ...] = (
    ("/operator/admin/users/", "operator.user_admin"),
    ("/operator/admin/users", "operator.user_admin"),
    ("/operator/control-plane/versions/", "operator.control_plane_versions"),
    ("/operator/control-plane/versions", "operator.control_plane_versions"),
    ("/operator/defaults", "operator.defaults"),
    ("/operator/trigger-run", "operator.trigger_run"),
    ("/operator/recent-runs", "operator.recent_runs"),
    ("/operator/delivery", "operator.delivery"),
    ("/operator/explain-audit", "operator.explain_audit"),
    ("/operator/readiness", "operator.readiness"),
    ("/operator/forbidden", "operator.forbidden"),
    ("/operator/dashboard", "operator.dashboard"),
    ("/operator", "operator.dashboard"),
)


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    page_key: str | None
    action_key: str | None
    message: str | None


def _normalize_role_values(roles: Iterable[Role | str]) -> frozenset[str]:
    normalized: set[str] = set()
    for role in roles:
        value = role.value if isinstance(role, Role) else str(role).strip().lower()
        if value:
            normalized.add(value)
    return frozenset(normalized)


def _path_matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _allowed_by_rule(
    *,
    rule_roles: frozenset[str],
    role_values: frozenset[str],
) -> bool:
    return bool(rule_roles.intersection(role_values))


def resolve_page_key(*, path: str) -> str | None:
    if "/operator/admin/users/" in path and "/credentials" in path:
        return "operator.user_credentials_admin"
    for prefix, page_key in _PAGE_PATH_RULES:
        if _path_matches(path, prefix):
            return page_key
    return None


def resolve_action_key(*, method: str, path: str) -> str | None:
    if method.upper() != "POST":
        return None
    if _path_matches(path, "/operator/defaults"):
        return "operator.defaults.update"
    if _path_matches(path, "/operator/trigger-run"):
        return "operator.trigger_run.submit"
    if "/operator/control-plane/versions/" in path and "/actions/" in path:
        return "operator.control_plane.lifecycle.transition"
    if path.endswith("/evidence") and "/operator/control-plane/versions/" in path:
        return "operator.control_plane.evidence.record"
    if "/operator/admin/users/" in path and "/credentials/" in path:
        return "operator.user_credentials.manage"
    if _path_matches(path, "/operator/admin/users"):
        return "operator.user_admin.manage"
    return None


def access_denied_message(*, page_key: str | None) -> str:
    if page_key in {"operator.user_admin", "operator.user_credentials_admin"}:
        return (
            "Access denied for your role on this page. "
            "User/role/password administration is admin_operator-only."
        )
    if page_key == "operator.control_plane_versions":
        return (
            "Access denied for your role on this page. "
            "Control-plane pages are limited to admin_operator, data_engineer, "
            "and ml_analyst."
        )
    return (
        "Access denied for your role on this page. "
        "Your account is signed in, but this surface is not assigned to your role."
    )


def action_denied_message(*, action_key: str) -> str:
    if action_key == "operator.control_plane.lifecycle.transition":
        return (
            "Access denied for this action. "
            "Lifecycle transition actions are admin_operator-only."
        )
    if action_key == "operator.control_plane.evidence.record":
        return (
            "Access denied for this action. "
            "Evidence recording is limited to admin_operator and ml_analyst."
        )
    return (
        "Access denied for this action. "
        "You can view this page, but your role cannot execute this operation."
    )


def evaluate_access(
    *,
    roles: tuple[Role, ...],
    path: str,
    method: str,
) -> AccessDecision:
    role_values = _normalize_role_values(roles)
    if not role_values:
        return AccessDecision(
            allowed=False,
            page_key=None,
            action_key=None,
            message=access_denied_message(page_key=None),
        )

    page_key = resolve_page_key(path=path)
    if page_key is None:
        return AccessDecision(
            allowed=False,
            page_key=None,
            action_key=None,
            message=access_denied_message(page_key=None),
        )
    page_rule = PAGE_ACCESS_MATRIX.get(page_key, frozenset())
    if not _allowed_by_rule(rule_roles=page_rule, role_values=role_values):
        return AccessDecision(
            allowed=False,
            page_key=page_key,
            action_key=None,
            message=access_denied_message(page_key=page_key),
        )

    action_key = resolve_action_key(method=method, path=path)
    if action_key is not None:
        action_rule = ACTION_ACCESS_MATRIX.get(action_key, frozenset())
        if not _allowed_by_rule(rule_roles=action_rule, role_values=role_values):
            return AccessDecision(
                allowed=False,
                page_key=page_key,
                action_key=action_key,
                message=action_denied_message(action_key=action_key),
            )
    return AccessDecision(
        allowed=True,
        page_key=page_key,
        action_key=action_key,
        message=None,
    )


def is_action_allowed(*, roles: tuple[Role, ...], action_key: str) -> bool:
    role_values = _normalize_role_values(roles)
    return _allowed_by_rule(
        rule_roles=ACTION_ACCESS_MATRIX.get(action_key, frozenset()),
        role_values=role_values,
    )


def filtered_nav_items(
    *,
    nav_items: list[dict[str, str]],
    roles: tuple[Role, ...],
) -> list[dict[str, str]]:
    role_values = _normalize_role_values(roles)
    filtered: list[dict[str, str]] = []
    for item in nav_items:
        path = str(item.get("path") or "")
        if not path:
            continue
        if _allowed_by_rule(
            rule_roles=NAV_VISIBILITY_MATRIX.get(path, frozenset()),
            role_values=role_values,
        ):
            filtered.append(item)
    if _allowed_by_rule(
        rule_roles=NAV_VISIBILITY_MATRIX["/operator/control-plane/versions"],
        role_values=role_values,
    ) and not any(
        str(item.get("path") or "") == "/operator/control-plane/versions"
        for item in filtered
    ):
        filtered.append(
            {
                "path": "/operator/control-plane/versions",
                "label": "Control-Plane Versions",
            }
        )
    return filtered


def show_control_plane_nav_fallback(*, roles: tuple[Role, ...]) -> bool:
    role_values = _normalize_role_values(roles)
    return _allowed_by_rule(
        rule_roles=NAV_VISIBILITY_MATRIX["/operator/control-plane/versions"],
        role_values=role_values,
    )


def visible_guidance_roles(*, roles: tuple[Role, ...]) -> tuple[str, ...]:
    role_values = _normalize_role_values(roles)
    if ROLE_ADMIN in role_values:
        return ROLE_GUIDANCE_ORDER
    return tuple(role for role in ROLE_GUIDANCE_ORDER if role in role_values)
