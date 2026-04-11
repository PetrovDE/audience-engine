from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pipelines.minimal_slice import user_login
from pipelines.minimal_slice.user_login_service import AuthenticatedUser, LoginResult
from services.retrieval_api import app as app_module
from services.retrieval_api import operator_user_admin_ui

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE_OPERATOR_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("OPERATOR_UI_USERNAME", "")
    monkeypatch.setenv("OPERATOR_UI_PASSWORD", "")
    client.cookies.clear()


def test_persisted_user_login_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    persisted_user = AuthenticatedUser(
        user_id="c72b0ecb-c7e2-41e2-9c12-8e2bfd7d4cba",
        username="alice.admin",
        roles=("admin_operator", "data_engineer"),
        primary_role="admin_operator",
    )

    monkeypatch.setattr(
        user_login,
        "verify_login",
        lambda username, password: LoginResult(
            user=persisted_user,
            require_password_reset=False,
        )
        if username == "alice.admin" and password == "Passw0rd!"
        else None,
    )
    monkeypatch.setattr(
        user_login,
        "resolve_authenticated_user",
        lambda user_id: persisted_user if user_id == persisted_user.user_id else None,
    )
    monkeypatch.setattr(
        operator_user_admin_ui.user_admin,
        "list_users",
        lambda **kwargs: [],
    )

    login = client.post(
        "/operator/login",
        data={
            "username": "alice.admin",
            "password": "Passw0rd!",
            "next": "/operator/admin/users",
        },
        follow_redirects=False,
    )

    assert login.status_code == 303
    assert "ae_operator_session=" in (login.headers.get("set-cookie") or "")

    users = client.get("/operator/admin/users", follow_redirects=False)
    assert users.status_code == 200


def test_persisted_login_rejects_invalid_or_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(user_login, "verify_login", lambda username, password: None)

    response = client.post(
        "/operator/login",
        data={
            "username": "inactive.user",
            "password": "WrongPass123!",
            "next": "/operator/dashboard",
        },
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert "Invalid username or password." in response.text


def _login_with_identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity: AuthenticatedUser,
    next_path: str = "/operator/dashboard",
) -> None:
    monkeypatch.setattr(
        user_login,
        "verify_login",
        lambda **kwargs: LoginResult(user=identity, require_password_reset=False),
    )
    monkeypatch.setattr(
        user_login,
        "resolve_authenticated_user",
        lambda **kwargs: identity,
    )
    login = client.post(
        "/operator/login",
        data={
            "username": identity.username,
            "password": "Passw0rd!",
            "next": next_path,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303


def _role_entry_points_fragment(html: str) -> str:
    marker = 'data-testid="role-surface-guidance"'
    start = html.find(marker)
    if start < 0:
        return ""
    end = html.find("</section>", start)
    if end < 0:
        return html[start:]
    return html[start:end]


@pytest.mark.parametrize(
    ("username", "roles", "primary_role"),
    [
        ("data.engineer", ("data_engineer",), "data_engineer"),
        ("ml.analyst", ("ml_analyst",), "ml_analyst"),
        ("campaign.user", ("campaign_user",), "campaign_user"),
    ],
)
def test_non_admin_roles_can_login_and_reach_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    username: str,
    roles: tuple[str, ...],
    primary_role: str,
) -> None:
    identity = AuthenticatedUser(
        user_id=f"{username}-id",
        username=username,
        roles=roles,
        primary_role=primary_role,
    )
    monkeypatch.setattr(
        user_login,
        "verify_login",
        lambda **kwargs: LoginResult(user=identity, require_password_reset=False),
    )
    monkeypatch.setattr(
        user_login,
        "resolve_authenticated_user",
        lambda **kwargs: identity,
    )

    login = client.post(
        "/operator/login",
        data={
            "username": username,
            "password": "Passw0rd!",
            "next": "/operator/dashboard",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303

    dashboard = client.get("/operator/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200


def test_non_admin_is_blocked_from_user_admin_pages_with_clear_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = AuthenticatedUser(
        user_id="campaign-user-id",
        username="campaign.user",
        roles=("campaign_user",),
        primary_role="campaign_user",
    )
    monkeypatch.setattr(
        user_login,
        "verify_login",
        lambda **kwargs: LoginResult(user=identity, require_password_reset=False),
    )
    monkeypatch.setattr(
        user_login,
        "resolve_authenticated_user",
        lambda **kwargs: identity,
    )

    login = client.post(
        "/operator/login",
        data={
            "username": "campaign.user",
            "password": "Passw0rd!",
            "next": "/operator/dashboard",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303

    blocked = client.get("/operator/admin/users", follow_redirects=True)
    assert blocked.status_code == 403
    assert "Access denied for your role on this page." in blocked.text
    assert "admin_operator-only" in blocked.text


def test_role_guidance_admin_sees_all_role_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_with_identity(
        monkeypatch,
        identity=AuthenticatedUser(
            user_id="admin-id",
            username="admin.user",
            roles=("admin_operator",),
            primary_role="admin_operator",
        ),
    )

    dashboard = client.get("/operator/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200
    guidance = _role_entry_points_fragment(dashboard.text)
    assert "Admin/Operator" in guidance
    assert "Data Engineer" in guidance
    assert "ML Analyst" in guidance
    assert "Campaign User" in guidance


def test_role_guidance_single_role_user_sees_only_assigned_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_with_identity(
        monkeypatch,
        identity=AuthenticatedUser(
            user_id="ml-id",
            username="ml.user",
            roles=("ml_analyst",),
            primary_role="ml_analyst",
        ),
    )

    dashboard = client.get("/operator/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200
    guidance = _role_entry_points_fragment(dashboard.text)
    assert "ML Analyst" in guidance
    assert "Admin/Operator" not in guidance
    assert "Data Engineer" not in guidance
    assert "Campaign User" not in guidance


def test_role_guidance_multi_role_user_sees_only_assigned_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_with_identity(
        monkeypatch,
        identity=AuthenticatedUser(
            user_id="multi-id",
            username="multi.user",
            roles=("data_engineer", "ml_analyst"),
            primary_role="data_engineer",
        ),
    )

    dashboard = client.get("/operator/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200
    guidance = _role_entry_points_fragment(dashboard.text)
    assert "Data Engineer" in guidance
    assert "ML Analyst" in guidance
    assert "Admin/Operator" not in guidance
    assert "Campaign User" not in guidance


def test_campaign_role_guidance_hides_de_ml_admin_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_with_identity(
        monkeypatch,
        identity=AuthenticatedUser(
            user_id="campaign-id",
            username="campaign.user",
            roles=("campaign_user",),
            primary_role="campaign_user",
        ),
    )

    dashboard = client.get("/operator/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200
    guidance = _role_entry_points_fragment(dashboard.text)
    assert "Campaign User" in guidance
    assert "Data Engineer" not in guidance
    assert "ML Analyst" not in guidance
    assert "Admin/Operator" not in guidance
