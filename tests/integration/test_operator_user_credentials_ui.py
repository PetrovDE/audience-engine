from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.retrieval_api import app as app_module
from services.retrieval_api import operator_user_credentials_ui

client = TestClient(app_module.app)

OPERATOR_UI_USERNAME = "admin"
OPERATOR_UI_PASSWORD = "203217"
USER_ID = str(uuid4())


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE_OPERATOR_SESSION_SECRET", "test-session-secret")
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


def test_credentials_page_and_set_reset_password_flows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(
        operator_user_credentials_ui.user_admin,
        "get_user",
        lambda **kwargs: {
            "user_id": USER_ID,
            "username": "ops.user",
            "display_name": "Ops User",
            "email": "ops@example.com",
            "is_active": True,
            "roles": ("admin_operator",),
            "created_at": "2026-04-11T10:00:00+00:00",
            "updated_at": "2026-04-11T10:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        operator_user_credentials_ui.user_login,
        "credential_status",
        lambda **kwargs: {
            "has_credentials": True,
            "require_password_reset": False,
            "password_updated_at": "2026-04-11T10:10:00+00:00",
        },
    )
    monkeypatch.setattr(
        operator_user_credentials_ui.user_login,
        "set_password",
        lambda **kwargs: captured.append({"action": "set", **kwargs})
        or {
            "user_id": kwargs["user_id"],
            "has_credentials": True,
            "require_password_reset": kwargs["require_password_reset"],
            "password_updated_at": "2026-04-11T10:20:00+00:00",
        },
    )
    monkeypatch.setattr(
        operator_user_credentials_ui.user_login,
        "reset_password",
        lambda **kwargs: captured.append({"action": "reset", **kwargs})
        or {
            "user_id": kwargs["user_id"],
            "has_credentials": True,
            "require_password_reset": True,
            "password_updated_at": "2026-04-11T10:30:00+00:00",
        },
    )

    _login()

    page = client.get(f"/operator/admin/users/{USER_ID}/credentials")
    assert page.status_code == 200
    assert "Credentials Configured" in page.text
    assert "Password Updated At" in page.text

    set_response = client.post(
        f"/operator/admin/users/{USER_ID}/credentials/set-password",
        data={"new_password": "NewPass123!", "require_password_reset": "1"},
        follow_redirects=False,
    )
    assert set_response.status_code == 303

    reset_response = client.post(
        f"/operator/admin/users/{USER_ID}/credentials/reset-password",
        data={"temporary_password": "TempPass123!"},
        follow_redirects=False,
    )
    assert reset_response.status_code == 303

    assert len(captured) == 2
    assert captured[0]["action"] == "set"
    assert captured[0]["actor_id"] == "operator_ui_env:admin"
    assert captured[1]["action"] == "reset"
    assert captured[1]["actor_id"] == "operator_ui_env:admin"

