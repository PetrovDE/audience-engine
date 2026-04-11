from __future__ import annotations

import pytest

from services.retrieval_api import (
    app as app_module,
)
from services.retrieval_api import (
    operator_control_plane_management as control_plane_mgmt,
)
from services.retrieval_api import (
    operator_user_admin_ui as user_admin_ui,
)
from tests.integration.operator_ui_uat_helpers import (
    apply_auth_env,
    client,
    login,
    patch_common_operator_catalog,
)

RU_QUICK_START = (
    "\u0411\u044b\u0441\u0442\u0440\u044b\u0439 "
    "\u0441\u0442\u0430\u0440\u0442"
)
RU_UAT_PANEL = "\u0421\u0442\u0430\u0442\u0443\u0441 UAT-\u043f\u0430\u043a\u0430"
RU_CONTROL_PLANE_TITLE = (
    "\u0420\u0435\u0435\u0441\u0442\u0440 \u0432\u0435\u0440\u0441\u0438\u0439 "
    "Control-Plane"
)
RU_CONTROL_PLANE_RECENT = (
    "\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 "
    "lifecycle-\u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f"
)
RU_USERS_TITLE = (
    "\u0410\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0438\u0440\u043e\u0432"
    "\u0430\u043d\u0438\u0435 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442"
    "\u0435\u043b\u0435\u0439"
)
RU_USERS_CREATE = (
    "\u0421\u043e\u0437\u0434\u0430\u0442\u044c "
    "\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f"
)
RU_JOURNEY_DASHBOARD_SUMMARY = "Используйте этот снимок, чтобы подтвердить запускаемые пути"
RU_ROLE_GUIDANCE_ADMIN = "Начинайте со снимка готовности, выбранных дефолтов"
RU_UAT_CHECK_NAV = "Основная навигация открывает ключевые UAT-страницы"
EN_JOURNEY_DASHBOARD_SUMMARY = (
    "Use this snapshot to confirm runnable paths before changing defaults or triggering runs."
)
EN_ROLE_GUIDANCE_ADMIN = (
    "Start from readiness snapshot, selected defaults, and primary orchestration entrypoint."
)
EN_UAT_CHECK_NAV = "Main navigation exposes key UAT pages"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    apply_auth_env(monkeypatch)


def test_language_defaults_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_common_operator_catalog(monkeypatch)
    login()

    response = client.get("/operator/dashboard")

    assert response.status_code == 200
    assert '<html lang="en">' in response.text
    assert "Quick Start" in response.text


def test_language_switch_to_russian_persists_in_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    login()

    switched = client.post(
        "/operator/language",
        data={"language": "ru", "next": "/operator/dashboard"},
        follow_redirects=False,
    )

    assert switched.status_code == 303
    assert switched.headers["location"] == "/operator/dashboard"
    assert "ae_operator_lang=ru" in (switched.headers.get("set-cookie") or "")

    response = client.get("/operator/dashboard")

    assert response.status_code == 200
    assert '<html lang="ru">' in response.text
    assert RU_QUICK_START in response.text
    assert RU_UAT_PANEL in response.text
    assert RU_JOURNEY_DASHBOARD_SUMMARY in response.text
    assert RU_ROLE_GUIDANCE_ADMIN in response.text
    assert RU_UAT_CHECK_NAV in response.text
    assert EN_JOURNEY_DASHBOARD_SUMMARY not in response.text
    assert EN_ROLE_GUIDANCE_ADMIN not in response.text
    assert EN_UAT_CHECK_NAV not in response.text


def test_unknown_language_cookie_falls_back_to_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    login()

    client.cookies.set("ae_operator_lang", "de")

    response = client.get("/operator/dashboard")

    assert response.status_code == 200
    assert '<html lang="en">' in response.text
    assert "Quick Start" in response.text


def test_russian_labels_render_on_control_plane_and_user_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    monkeypatch.setattr(
        app_module.control_plane_registry,
        "list_versions",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        control_plane_mgmt,
        "list_recent_registry_lifecycle_actions",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        user_admin_ui.user_admin,
        "list_users",
        lambda **kwargs: [],
    )

    login(next_path="/operator/control-plane/versions")
    client.post(
        "/operator/language",
        data={"language": "ru", "next": "/operator/control-plane/versions"},
        follow_redirects=False,
    )

    control_plane_page = client.get("/operator/control-plane/versions")
    assert control_plane_page.status_code == 200
    assert RU_CONTROL_PLANE_TITLE in control_plane_page.text
    assert RU_CONTROL_PLANE_RECENT in control_plane_page.text

    users_page = client.get("/operator/admin/users")
    assert users_page.status_code == 200
    assert RU_USERS_TITLE in users_page.text
    assert RU_USERS_CREATE in users_page.text


def test_topbar_language_switcher_renders_with_account_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_common_operator_catalog(monkeypatch)
    login()

    response = client.get("/operator/dashboard")

    assert response.status_code == 200
    html = response.text
    assert 'data-testid="topbar-account-controls"' in html
    assert 'data-testid="topbar-language-switcher"' in html
    assert 'class="session-meta"' in html

    account_cluster = html.split('data-testid="topbar-account-controls"', 1)[1]
    account_cluster = account_cluster.split("</header>", 1)[0]
    assert 'action="/operator/logout"' in account_cluster
    assert 'data-testid="topbar-language-switcher"' in account_cluster
    assert account_cluster.index('action="/operator/logout"') < account_cluster.index(
        'data-testid="topbar-language-switcher"'
    )
