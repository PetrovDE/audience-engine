from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from pipelines.minimal_slice.user_admin_service import UserAdminService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeUserAdminRepository:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.users_by_username: dict[str, str] = {}
        self.roles: dict[str, set[str]] = {}
        self.audit: list[dict] = []

    def create_user(self, *, username, display_name, email, is_active, actor_id):  # noqa: ANN001
        user_id = str(uuid4())
        row = {
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
            "email": email,
            "is_active": is_active,
            "created_by": actor_id,
            "updated_by": actor_id,
            "created_at": _now(),
            "updated_at": _now(),
            "roles": (),
        }
        self.users[user_id] = row
        self.users_by_username[username] = user_id
        self.roles[user_id] = set()
        return dict(row)

    def list_users(self, *, include_inactive):  # noqa: ANN001
        rows = [dict(row) for row in self.users.values()]
        if not include_inactive:
            rows = [row for row in rows if row["is_active"]]
        for row in rows:
            row["roles"] = tuple(sorted(self.roles[row["user_id"]]))
        return rows

    def get_user_by_id(self, *, user_id):  # noqa: ANN001
        row = self.users.get(user_id)
        if row is None:
            return None
        payload = dict(row)
        payload["roles"] = tuple(sorted(self.roles[user_id]))
        return payload

    def get_user_by_username(self, *, username):  # noqa: ANN001
        user_id = self.users_by_username.get(username)
        if not user_id:
            return None
        return self.get_user_by_id(user_id=user_id)

    def update_user_profile(self, *, user_id, display_name, email, actor_id):  # noqa: ANN001
        row = self.users.get(user_id)
        if row is None:
            return None
        if display_name is not None:
            row["display_name"] = display_name
        if email is not None:
            row["email"] = email
        row["updated_by"] = actor_id
        row["updated_at"] = _now()
        return self.get_user_by_id(user_id=user_id)

    def set_user_active(self, *, user_id, is_active, actor_id):  # noqa: ANN001
        row = self.users.get(user_id)
        if row is None:
            return None
        row["is_active"] = is_active
        row["updated_by"] = actor_id
        row["updated_at"] = _now()
        return self.get_user_by_id(user_id=user_id)

    def list_user_roles(self, *, user_id):  # noqa: ANN001
        return tuple(sorted(self.roles.get(user_id, set())))

    def assign_role(self, *, user_id, role, actor_id):  # noqa: ANN001
        row = self.users.get(user_id)
        if row is None:
            return False
        before = len(self.roles[user_id])
        self.roles[user_id].add(role)
        row["updated_by"] = actor_id
        row["updated_at"] = _now()
        return len(self.roles[user_id]) > before

    def remove_role(self, *, user_id, role, actor_id):  # noqa: ANN001
        row = self.users.get(user_id)
        if row is None or role not in self.roles[user_id]:
            return False
        self.roles[user_id].remove(role)
        row["updated_by"] = actor_id
        row["updated_at"] = _now()
        return True

    def append_audit_entry(self, *, audit_action, actor_id, target_user_id, details):  # noqa: ANN001
        payload = {
            "audit_action": audit_action,
            "actor_id": actor_id,
            "target_user_id": target_user_id,
            "details": details or {},
            "action_ts": _now(),
        }
        self.audit.append(payload)
        return payload

    def list_audit_entries(self, *, target_user_id=None, limit=50):  # noqa: ANN001
        rows = self.audit
        if target_user_id:
            rows = [row for row in rows if row["target_user_id"] == target_user_id]
        return list(reversed(rows))[:limit]


@pytest.fixture()
def service() -> UserAdminService:
    return UserAdminService(repository=_FakeUserAdminRepository())


def test_create_user_records_initial_roles(service: UserAdminService) -> None:
    created = service.create_user(
        username="alice.ops",
        display_name="Alice Operator",
        email="alice@example.com",
        initial_roles=["admin_operator", "campaign_user"],
        is_active=True,
        actor_id="operator_ui:admin",
    )
    assert created["username"] == "alice.ops"
    assert set(created["roles"]) == {"admin_operator", "campaign_user"}
    assert created["is_active"] is True


def test_assign_and_remove_role_updates_roles(service: UserAdminService) -> None:
    created = service.create_user(
        username="sam.ml",
        display_name="Sam Analyst",
        email=None,
        initial_roles=["ml_analyst"],
        is_active=True,
        actor_id="operator_ui:admin",
    )
    user_id = created["user_id"]

    effective_after_assign = service.assign_role(
        user_id=user_id,
        role="data_engineer",
        actor_id="operator_ui:admin",
    )
    assert set(effective_after_assign) == {"ml_analyst", "data_engineer"}

    effective_after_remove = service.remove_role(
        user_id=user_id,
        role="ml_analyst",
        actor_id="operator_ui:admin",
    )
    assert effective_after_remove == ("data_engineer",)


def test_invalid_role_is_rejected(service: UserAdminService) -> None:
    with pytest.raises(ValueError, match="Invalid role"):
        service.create_user(
            username="bad.role",
            display_name="Bad Role",
            email=None,
            initial_roles=["super_admin"],
            is_active=True,
            actor_id="operator_ui:admin",
        )


def test_activate_deactivate_user_flow(service: UserAdminService) -> None:
    created = service.create_user(
        username="case.user",
        display_name="Case User",
        email=None,
        initial_roles=["campaign_user"],
        is_active=True,
        actor_id="operator_ui:admin",
    )
    user_id = created["user_id"]

    deactivated = service.set_user_active(
        user_id=user_id,
        is_active=False,
        actor_id="operator_ui:admin",
    )
    assert deactivated["is_active"] is False

    reactivated = service.set_user_active(
        user_id=user_id,
        is_active=True,
        actor_id="operator_ui:admin",
    )
    assert reactivated["is_active"] is True
