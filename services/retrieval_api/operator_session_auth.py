from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

SESSION_SECRET_ENV = "AE_OPERATOR_SESSION_SECRET"
_LEGACY_PASSWORD_ENV = "OPERATOR_UI_PASSWORD"
_SESSION_VERSION = "v1"


@dataclass(frozen=True)
class SessionSubject:
    subject_type: str
    subject_id: str


def _session_secret() -> str | None:
    explicit = os.getenv(SESSION_SECRET_ENV, "").strip()
    if explicit:
        return explicit
    legacy = os.getenv(_LEGACY_PASSWORD_ENV, "").strip()
    return legacy if legacy else None


def session_signing_is_configured() -> bool:
    return _session_secret() is not None


def _sign_payload(payload: str, *, secret: str) -> str:
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def issue_session_cookie_value(*, subject_type: str, subject_id: str) -> str:
    secret = _session_secret()
    if secret is None:
        raise ValueError(
            f"Session signing is not configured. Set {SESSION_SECRET_ENV}."
        )
    payload = f"{_SESSION_VERSION}|{subject_type}|{subject_id}"
    signature = _sign_payload(payload, secret=secret)
    return f"{payload}|{signature}"


def resolve_session_subject(cookie_value: str | None) -> SessionSubject | None:
    secret = _session_secret()
    if cookie_value is None or secret is None:
        return None
    parts = cookie_value.split("|")
    if len(parts) != 4:
        return None
    version, subject_type, subject_id, signature = parts
    if version != _SESSION_VERSION or not subject_type or not subject_id:
        return None
    payload = f"{version}|{subject_type}|{subject_id}"
    expected = _sign_payload(payload, secret=secret)
    if not hmac.compare_digest(signature, expected):
        return None
    return SessionSubject(subject_type=subject_type, subject_id=subject_id)

