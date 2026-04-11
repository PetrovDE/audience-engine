from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pipelines.minimal_slice.user_login_service import UserLoginService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeUserRepo:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}

    def add_user(
        self,
        *,
        username: str,
        roles: tuple[str, ...],
        is_active: bool = True,
    ) -> str:
        user_id = str(uuid4())
        self.users[user_id] = {
            "user_id": user_id,
            "username": username,
            "display_name": username,
            "email": None,
            "is_active": is_active,
            "roles": roles,
            "created_at": _now(),
            "updated_at": _now(),
        }
        return user_id

    def get_user_by_id(self, *, user_id):  # noqa: ANN001
        return self.users.get(user_id)

    def get_user_by_username(self, *, username):  # noqa: ANN001
        for row in self.users.values():
            if row["username"] == username:
                return row
        return None


class _FakeCredentialsRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def upsert_password_hash(self, **kwargs):  # noqa: ANN003
        row = {
            "user_id": kwargs["user_id"],
            "password_hash": kwargs["password_hash"],
            "require_password_reset": kwargs["require_password_reset"],
            "password_updated_by": kwargs["password_updated_by"],
            "password_updated_at": _now(),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.rows[kwargs["user_id"]] = row
        return row

    def get_credentials_by_user_id(self, *, user_id):  # noqa: ANN001
        return self.rows.get(user_id)


class _FakeAuditRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append_audit_entry(self, **kwargs):  # noqa: ANN003
        self.rows.append(kwargs)
        return kwargs


def test_set_password_hashes_and_audits() -> None:
    users = _FakeUserRepo()
    credentials = _FakeCredentialsRepo()
    audit = _FakeAuditRepo()
    user_id = users.add_user(username="admin", roles=("admin_operator",))
    service = UserLoginService(
        user_repository=users,
        credentials_repository=credentials,
        audit_repository=audit,
    )

    result = service.set_password(
        user_id=user_id,
        new_password="AdminPass123!",
        actor_id="operator_ui:admin",
    )

    stored = credentials.get_credentials_by_user_id(user_id=user_id)
    assert stored is not None
    assert stored["password_hash"] != "AdminPass123!"
    assert result["has_credentials"] is True
    assert audit.rows[-1]["audit_action"] == "password_set"


def test_inactive_user_login_is_rejected() -> None:
    users = _FakeUserRepo()
    credentials = _FakeCredentialsRepo()
    audit = _FakeAuditRepo()
    user_id = users.add_user(
        username="inactive.user",
        roles=("admin_operator",),
        is_active=False,
    )
    service = UserLoginService(
        user_repository=users,
        credentials_repository=credentials,
        audit_repository=audit,
    )
    service.set_password(
        user_id=user_id,
        new_password="InactivePass123!",
        actor_id="operator_ui:admin",
    )

    login = service.verify_login(username="inactive.user", password="InactivePass123!")
    assert login is None


def test_successful_login_returns_roles_from_assignments() -> None:
    users = _FakeUserRepo()
    credentials = _FakeCredentialsRepo()
    audit = _FakeAuditRepo()
    user_id = users.add_user(
        username="multi.role",
        roles=("campaign_user", "ml_analyst", "admin_operator"),
        is_active=True,
    )
    service = UserLoginService(
        user_repository=users,
        credentials_repository=credentials,
        audit_repository=audit,
    )
    service.set_password(
        user_id=user_id,
        new_password="MyPassword123!",
        actor_id="operator_ui:admin",
    )

    login = service.verify_login(username="multi.role", password="MyPassword123!")

    assert login is not None
    assert login.user.user_id == user_id
    assert login.user.primary_role == "admin_operator"
    assert set(login.user.roles) == {"campaign_user", "ml_analyst", "admin_operator"}

