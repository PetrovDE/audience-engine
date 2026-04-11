from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import Response

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "ru")
LANGUAGE_COOKIE = "ae_operator_lang"
LANGUAGE_COOKIE_MAX_AGE_SECONDS = 90 * 24 * 60 * 60
LANGUAGE_SWITCH_PATH = "/operator/language"

_MODULE_DIR = Path(__file__).resolve().parent
_LOCALES_DIR = _MODULE_DIR / "locales"
_CATALOG_FILES = {
    "en": _LOCALES_DIR / "operator.en.json",
    "ru": _LOCALES_DIR / "operator.ru.json",
}

NAV_LABEL_KEYS: dict[str, str] = {
    "/operator/dashboard": "nav.dashboard",
    "/operator/defaults": "nav.defaults",
    "/operator/trigger-run": "nav.trigger_run",
    "/operator/recent-runs": "nav.recent_runs",
    "/operator/delivery": "nav.delivery",
    "/operator/explain-audit": "nav.explain_audit",
    "/operator/readiness": "nav.readiness",
    "/operator/control-plane/versions": "nav.control_plane_versions",
    "/operator/admin/users": "nav.user_admin",
}

_LANGUAGE_OPTION_KEYS = {
    "en": "language.option.english",
    "ru": "language.option.russian",
}

_ACCESS_MESSAGE_KEYS = {
    (
        "Access denied for your role on this page. "
        "User/role/password administration is admin_operator-only."
    ): "forbidden.access.user_admin_admin_only",
    (
        "Access denied for your role on this page. "
        "Control-plane pages are limited to admin_operator, data_engineer, "
        "and ml_analyst."
    ): "forbidden.access.control_plane_role_limited",
    (
        "Access denied for your role on this page. "
        "Your account is signed in, but this surface is not assigned to your role."
    ): "forbidden.access.page_not_assigned",
    (
        "Access denied for this action. "
        "Lifecycle transition actions are admin_operator-only."
    ): "forbidden.access.lifecycle_admin_only",
    (
        "Access denied for this action. "
        "Evidence recording is limited to admin_operator and ml_analyst."
    ): "forbidden.access.evidence_role_limited",
    (
        "Access denied for this action. "
        "You can view this page, but your role cannot execute this operation."
    ): "forbidden.access.action_not_allowed",
}


@dataclass(frozen=True)
class Translator:
    language: str

    def __call__(self, key: str, **params: Any) -> str:
        default = params.pop("default", None)
        return translate(
            key,
            language=self.language,
            default=default,
            **params,
        )


@lru_cache(maxsize=1)
def _catalog_by_language() -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {code: {} for code in SUPPORTED_LANGUAGES}
    for language, path in _CATALOG_FILES.items():
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            continue
        normalized: dict[str, str] = {}
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            if not isinstance(value, str):
                continue
            normalized[key] = value
        catalog[language] = normalized
    return catalog


def normalize_language(language: str | None) -> str:
    if language is None:
        return DEFAULT_LANGUAGE
    normalized = language.strip().lower()
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    return DEFAULT_LANGUAGE


def request_language(request: Request) -> str:
    query_language = request.query_params.get("lang")
    if query_language:
        return normalize_language(query_language)
    cookie_language = request.cookies.get(LANGUAGE_COOKIE)
    return normalize_language(cookie_language)


def translate(
    key: str,
    *,
    language: str,
    default: str | None = None,
    **params: Any,
) -> str:
    catalog = _catalog_by_language()
    resolved_language = normalize_language(language)

    value = catalog.get(resolved_language, {}).get(key)
    if value is None:
        value = catalog.get(DEFAULT_LANGUAGE, {}).get(key)
    if value is None:
        value = default if default is not None else key

    if params:
        try:
            return value.format(**params)
        except (KeyError, ValueError):
            return value
    return value


def translate_for_request(
    request: Request,
    key: str,
    *,
    default: str | None = None,
    **params: Any,
) -> str:
    return translate(
        key,
        language=request_language(request),
        default=default,
        **params,
    )


def translator_for_request(request: Request) -> Translator:
    return Translator(language=request_language(request))


def language_options(*, translator: Translator) -> list[dict[str, str]]:
    return [
        {
            "code": code,
            "label": translator(
                _LANGUAGE_OPTION_KEYS[code],
                default=code,
            ),
        }
        for code in SUPPORTED_LANGUAGES
    ]


def localize_nav_items(
    *,
    nav_items: list[dict[str, str]],
    translator: Translator,
) -> list[dict[str, str]]:
    localized: list[dict[str, str]] = []
    for item in nav_items:
        path = str(item.get("path") or "")
        key = NAV_LABEL_KEYS.get(path)
        if key is None:
            localized.append(dict(item))
            continue
        localized_item = dict(item)
        localized_item["label"] = translator(
            key,
            default=str(item.get("label") or path),
        )
        localized.append(localized_item)
    return localized


def apply_template_context(
    *,
    request: Request,
    context: dict[str, Any],
) -> dict[str, Any]:
    translator = translator_for_request(request)
    context["lang"] = translator.language
    context["t"] = translator
    context["language_switch_path"] = LANGUAGE_SWITCH_PATH
    context["language_options"] = language_options(translator=translator)

    nav_items = context.get("nav_items")
    if isinstance(nav_items, list):
        context["nav_items"] = localize_nav_items(
            nav_items=nav_items,
            translator=translator,
        )
    return context


def set_language_cookie(response: Response, language: str) -> None:
    response.set_cookie(
        key=LANGUAGE_COOKIE,
        value=normalize_language(language),
        max_age=LANGUAGE_COOKIE_MAX_AGE_SECONDS,
        samesite="lax",
    )


def localize_access_message(*, request: Request, message: str) -> str:
    key = _ACCESS_MESSAGE_KEYS.get(message)
    if key is None:
        return message
    return translate_for_request(request, key, default=message)


def current_path_with_query(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        return f"{path}?{request.url.query}"
    return path
