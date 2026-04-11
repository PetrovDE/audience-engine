from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from pipelines.minimal_slice.access_roles import ROLE_VALUES
from services.retrieval_api import app as app_module
from services.retrieval_api import operator_user_admin_ui as user_admin_ui_module

client = TestClient(app_module.app)

CAMPAIGN_KEY = "campaign-test-key"
ADMIN_KEY = "admin-test-key"
OPERATOR_UI_USERNAME = "admin"
OPERATOR_UI_PASSWORD = "203217"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE_CAMPAIGN_API_KEYS", CAMPAIGN_KEY)
    monkeypatch.setenv("AE_ADMIN_API_KEYS", ADMIN_KEY)
    monkeypatch.setenv("OPERATOR_UI_USERNAME", OPERATOR_UI_USERNAME)
    monkeypatch.setenv("OPERATOR_UI_PASSWORD", OPERATOR_UI_PASSWORD)
    client.cookies.clear()


def _login() -> None:
    response = client.post(
        "/operator/login",
        data={
            "username": OPERATOR_UI_USERNAME,
            "password": OPERATOR_UI_PASSWORD,
            "next": "/operator/admin/users",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _install_fake_user_admin(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    users: dict[str, dict] = {}
    audit: list[dict] = []

    admin_id = str(uuid4())
    users[admin_id] = {
        "user_id": admin_id,
        "username": "admin",
        "display_name": "Admin Operator",
        "email": "admin@example.com",
        "is_active": True,
        "roles": ("admin_operator",),
        "created_at": "2026-04-11T10:00:00+00:00",
        "updated_at": "2026-04-11T10:00:00+00:00",
    }

    def _list_users(*, include_inactive=True):  # noqa: ANN001
        rows = list(users.values())
        if not include_inactive:
            rows = [row for row in rows if row["is_active"]]
        return sorted(rows, key=lambda row: row["username"])

    def _get_user(*, user_id):  # noqa: ANN001
        return users.get(user_id)

    def _create_user(  # noqa: ANN001
        *,
        username,
        display_name=None,
        email=None,
        initial_roles=(),
        is_active=True,
        actor_id,
    ):
        resolved_roles = tuple(initial_roles)
        invalid = [role for role in resolved_roles if role not in ROLE_VALUES]
        if invalid:
            raise ValueError(f"Invalid role '{invalid[0]}'.")
        user_id = str(uuid4())
        users[user_id] = {
            "user_id": user_id,
            "username": username.strip().lower(),
            "display_name": display_name or username.strip(),
            "email": email,
            "is_active": is_active,
            "roles": tuple(sorted(set(resolved_roles))),
            "created_at": "2026-04-11T10:01:00+00:00",
            "updated_at": "2026-04-11T10:01:00+00:00",
        }
        audit.append(
            {
                "audit_action": "user_created",
                "actor_id": actor_id,
                "target_user_id": user_id,
                "details": {"roles": list(resolved_roles)},
                "action_ts": "2026-04-11T10:01:00+00:00",
            }
        )
        return users[user_id]

    def _update_user_profile(*, user_id, display_name=None, email=None, actor_id):  # noqa: ANN001
        user = users.get(user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        if display_name is not None:
            user["display_name"] = display_name
        if email is not None:
            user["email"] = email
        user["updated_at"] = "2026-04-11T10:02:00+00:00"
        audit.append(
            {
                "audit_action": "user_profile_updated",
                "actor_id": actor_id,
                "target_user_id": user_id,
                "details": {"display_name": user["display_name"]},
                "action_ts": "2026-04-11T10:02:00+00:00",
            }
        )
        return user

    def _set_user_active(*, user_id, is_active, actor_id):  # noqa: ANN001
        user = users.get(user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        user["is_active"] = is_active
        user["updated_at"] = "2026-04-11T10:03:00+00:00"
        audit.append(
            {
                "audit_action": "user_activated" if is_active else "user_deactivated",
                "actor_id": actor_id,
                "target_user_id": user_id,
                "details": {"is_active": is_active},
                "action_ts": "2026-04-11T10:03:00+00:00",
            }
        )
        return user

    def _assign_role(*, user_id, role, actor_id):  # noqa: ANN001
        if role not in ROLE_VALUES:
            raise ValueError(f"Invalid role '{role}'.")
        user = users.get(user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        roles = set(user["roles"])
        roles.add(role)
        user["roles"] = tuple(sorted(roles))
        audit.append(
            {
                "audit_action": "role_assigned",
                "actor_id": actor_id,
                "target_user_id": user_id,
                "details": {"role": role},
                "action_ts": "2026-04-11T10:04:00+00:00",
            }
        )
        return user["roles"]

    def _remove_role(*, user_id, role, actor_id):  # noqa: ANN001
        if role not in ROLE_VALUES:
            raise ValueError(f"Invalid role '{role}'.")
        user = users.get(user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        roles = set(user["roles"])
        roles.discard(role)
        user["roles"] = tuple(sorted(roles))
        audit.append(
            {
                "audit_action": "role_removed",
                "actor_id": actor_id,
                "target_user_id": user_id,
                "details": {"role": role},
                "action_ts": "2026-04-11T10:05:00+00:00",
            }
        )
        return user["roles"]

    def _list_audit_entries(*, target_user_id=None, limit=50):  # noqa: ANN001
        rows = audit
        if target_user_id is not None:
            rows = [row for row in rows if row["target_user_id"] == target_user_id]
        return list(reversed(rows))[:limit]

    monkeypatch.setattr(user_admin_ui_module.user_admin, "list_users", _list_users)
    monkeypatch.setattr(user_admin_ui_module.user_admin, "get_user", _get_user)
    monkeypatch.setattr(user_admin_ui_module.user_admin, "create_user", _create_user)
    monkeypatch.setattr(
        user_admin_ui_module.user_admin,
        "update_user_profile",
        _update_user_profile,
    )
    monkeypatch.setattr(
        user_admin_ui_module.user_admin,
        "set_user_active",
        _set_user_active,
    )
    monkeypatch.setattr(user_admin_ui_module.user_admin, "assign_role", _assign_role)
    monkeypatch.setattr(user_admin_ui_module.user_admin, "remove_role", _remove_role)
    monkeypatch.setattr(
        user_admin_ui_module.user_admin,
        "list_audit_entries",
        _list_audit_entries,
    )
    return users


def test_user_admin_surface_requires_operator_session() -> None:
    response = client.get("/operator/admin/users", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/operator/login")


def test_user_admin_surface_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    users = _install_fake_user_admin(monkeypatch)
    _login()

    listing = client.get("/operator/admin/users")
    assert listing.status_code == 200
    assert "User Administration" in listing.text
    assert "admin" in listing.text

    created = client.post(
        "/operator/admin/users",
        data={
            "username": "jane.ops",
            "display_name": "Jane Ops",
            "email": "jane@example.com",
            "roles": ["campaign_user"],
            "is_active": "1",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    detail_location = created.headers["location"]
    assert detail_location.startswith("/operator/admin/users/")
    user_id = detail_location.split("/operator/admin/users/", 1)[1].split("?", 1)[0]

    detail = client.get(f"/operator/admin/users/{user_id}")
    assert detail.status_code == 200
    assert "Jane Ops" in detail.text
    assert "Campaign User" in detail.text

    assign = client.post(
        f"/operator/admin/users/{user_id}/roles/assign",
        data={"role": "ml_analyst"},
        follow_redirects=False,
    )
    assert assign.status_code == 303
    assert "ml_analyst" in users[user_id]["roles"]

    remove = client.post(
        f"/operator/admin/users/{user_id}/roles/remove",
        data={"role": "campaign_user"},
        follow_redirects=False,
    )
    assert remove.status_code == 303
    assert "campaign_user" not in users[user_id]["roles"]

    deactivate = client.post(
        f"/operator/admin/users/{user_id}/deactivate",
        follow_redirects=False,
    )
    assert deactivate.status_code == 303
    assert users[user_id]["is_active"] is False

    activate = client.post(
        f"/operator/admin/users/{user_id}/activate",
        follow_redirects=False,
    )
    assert activate.status_code == 303
    assert users[user_id]["is_active"] is True


def test_user_admin_invalid_role_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_user_admin(monkeypatch)
    _login()

    response = client.post(
        "/operator/admin/users",
        data={
            "username": "invalid.role",
            "display_name": "Invalid Role",
            "email": "",
            "roles": ["unknown_role"],
            "is_active": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Invalid role" in response.text

