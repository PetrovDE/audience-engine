from __future__ import annotations

import base64
import json
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request


class AIHubProviderConfigError(RuntimeError):
    """Raised when AI Hub configuration is incomplete or invalid."""


class AIHubProviderAuthError(RuntimeError):
    """Raised when AI Hub authentication fails."""


class AIHubProviderTransientError(RuntimeError):
    """Raised when a transient AI Hub network or 5xx failure occurs."""


def _ssl_context(verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


@dataclass(frozen=True)
class AIHubAuthConfig:
    access_token: str
    token_url: str
    client_id: str
    client_secret: str
    username: str
    password: str
    timeout_seconds: float
    verify_ssl: bool
    retry_attempts: int


@dataclass(frozen=True)
class AIHubEmbeddingConfig:
    base_url: str
    model: str
    timeout_seconds: float
    verify_ssl: bool
    retry_attempts: int
    auth: AIHubAuthConfig


class AIHubTokenManager:
    def __init__(self, config: AIHubAuthConfig) -> None:
        self._config = config
        self._cached_token: str | None = None
        self._expires_at: datetime | None = None

    def get_token(self) -> str:
        static_token = self._config.access_token.strip()
        if static_token:
            return static_token

        if self._cached_token and self._expires_at:
            if datetime.now(timezone.utc) < self._expires_at:
                return self._cached_token

        token, expires_in = self._request_token()
        # Refresh one minute early to avoid near-expiry races.
        self._cached_token = token
        self._expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=max(60, expires_in - 60)
        )
        return token

    def clear_cached_token(self) -> None:
        self._cached_token = None
        self._expires_at = None

    def _request_token(self) -> tuple[str, int]:
        token_url = self._config.token_url.strip()
        required = {
            "AI_HUB_TOKEN_URL": token_url,
            "AI_HUB_CLIENT_ID": self._config.client_id,
            "AI_HUB_CLIENT_SECRET": self._config.client_secret,
            "AI_HUB_USERNAME": self._config.username,
            "AI_HUB_PASSWORD": self._config.password,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            fields = ", ".join(sorted(missing))
            raise AIHubProviderConfigError(
                "AI Hub token flow is configured but required fields are missing: "
                f"{fields}"
            )

        credentials = f"{self._config.client_id}:{self._config.client_secret}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        form = url_parse.urlencode(
            {
                "grant_type": "password",
                "username": self._config.username,
                "password": self._config.password,
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        request = url_request.Request(
            token_url,
            data=form,
            headers=headers,
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(1, self._config.retry_attempts + 1):
            try:
                with url_request.urlopen(
                    request,
                    timeout=self._config.timeout_seconds,
                    context=_ssl_context(self._config.verify_ssl),
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                token = str(payload.get("access_token") or "").strip()
                if not token:
                    raise AIHubProviderAuthError(
                        "AI Hub auth response did not include access_token"
                    )
                expires_in = int(payload.get("expires_in", 300))
                return token, max(60, expires_in)
            except url_error.HTTPError as exc:
                status = int(getattr(exc, "code", 0) or 0)
                if status in {401, 403}:
                    raise AIHubProviderAuthError(
                        f"AI Hub token request unauthorized (status={status})"
                    ) from exc
                if status in {408, 425, 429} or 500 <= status <= 599:
                    last_error = exc
                    if attempt < self._config.retry_attempts:
                        time.sleep(0.2 * attempt)
                        continue
                    raise AIHubProviderTransientError(
                        f"AI Hub token request transient HTTP failure (status={status})"
                    ) from exc
                raise AIHubProviderConfigError(
                    f"AI Hub token request failed (status={status})"
                ) from exc
            except (url_error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < self._config.retry_attempts:
                    time.sleep(0.2 * attempt)
                    continue
                raise AIHubProviderTransientError(
                    "AI Hub token request failed due to network/timeout error"
                ) from exc
        raise AIHubProviderTransientError(
            f"AI Hub token request failed after retries: {last_error}"
        )


class AIHubEmbeddingClient:
    def __init__(self, config: AIHubEmbeddingConfig) -> None:
        self._config = config
        self._token_manager = AIHubTokenManager(config.auth)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vectors.append(self._embed_single(text))
        return vectors

    def _embed_single(self, text: str) -> list[float]:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("AI Hub embedding input cannot be empty")
        url = (
            f"{self._config.base_url.rstrip('/')}/models/"
            f"{url_parse.quote(self._config.model)}/embed"
        )
        payload = json.dumps({"input": clean_text}).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(1, self._config.retry_attempts + 1):
            token = self._token_manager.get_token()
            request = url_request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with url_request.urlopen(
                    request,
                    timeout=self._config.timeout_seconds,
                    context=_ssl_context(self._config.verify_ssl),
                ) as response:
                    body = json.loads(response.read().decode("utf-8"))
                vector = _extract_embedding(body)
                if not vector:
                    raise AIHubProviderConfigError(
                        "AI Hub embedding response does not include a valid vector"
                    )
                return vector
            except url_error.HTTPError as exc:
                status = int(getattr(exc, "code", 0) or 0)
                if status in {401, 403}:
                    self._token_manager.clear_cached_token()
                    if attempt < self._config.retry_attempts:
                        continue
                    raise AIHubProviderAuthError(
                        f"AI Hub embedding unauthorized (status={status})"
                    ) from exc
                if status in {408, 425, 429} or 500 <= status <= 599:
                    last_error = exc
                    if attempt < self._config.retry_attempts:
                        time.sleep(0.2 * attempt)
                        continue
                    raise AIHubProviderTransientError(
                        f"AI Hub embedding transient HTTP failure (status={status})"
                    ) from exc
                raise AIHubProviderConfigError(
                    f"AI Hub embedding request failed (status={status})"
                ) from exc
            except (url_error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < self._config.retry_attempts:
                    time.sleep(0.2 * attempt)
                    continue
                raise AIHubProviderTransientError(
                    "AI Hub embedding request failed due to network/timeout error"
                ) from exc
        raise AIHubProviderTransientError(
            f"AI Hub embedding request failed after retries: {last_error}"
        )


def _extract_embedding(payload: Any) -> list[float]:
    if isinstance(payload, dict):
        candidate = payload.get("embedding")
        if isinstance(candidate, list):
            return [float(value) for value in candidate]
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            if isinstance(embeddings[0], list):
                return [float(value) for value in embeddings[0]]
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            nested = data[0].get("embedding")
            if isinstance(nested, list):
                return [float(value) for value in nested]
    return []
