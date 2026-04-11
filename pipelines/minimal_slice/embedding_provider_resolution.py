from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import control_plane_registry
from .config import (
    AI_HUB_ACCESS_TOKEN,
    AI_HUB_BASE_URL,
    AI_HUB_CLIENT_ID,
    AI_HUB_CLIENT_SECRET,
    AI_HUB_EMBEDDING_MODEL,
    AI_HUB_ENABLED,
    AI_HUB_PASSWORD,
    AI_HUB_TOKEN_URL,
    AI_HUB_USERNAME,
    EMBEDDING_PROVIDER_DEFAULT,
)
from .provider_identity import (
    PROVIDER_TYPE_AI_HUB,
    PROVIDER_TYPE_OLLAMA,
    parse_embedding_provider_identity,
)


class EmbeddingProviderResolutionError(ValueError):
    """Raised when embedding provider selection fails."""


@dataclass(frozen=True)
class EmbeddingProviderSelection:
    provider_type: str
    provider_key: str
    capability: str
    provider_model_ref: str
    model_version: str
    provider_config_ref: str | None
    model_version_id: str | None
    embedding_model_version_id: str | None
    resolution_source: str
    resolution_reason: str | None


def resolve_embedding_provider_selection(
    *,
    fallback_model_version: str,
) -> EmbeddingProviderSelection:
    active_row: dict[str, Any] | None = None
    registry_error: Exception | None = None
    try:
        active_row = control_plane_registry.get_active_version(
            entity_type="embedding_providers",
            entity_key=None,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime DB availability
        registry_error = exc

    if active_row is not None:
        return _selection_from_registry_row(
            active_row,
            fallback_model_version=fallback_model_version,
        )
    return _selection_from_defaults(
        fallback_model_version=fallback_model_version,
        registry_error=registry_error,
    )


def list_embedding_provider_candidates(
    *,
    fallback_model_version: str,
) -> list[dict[str, str]]:
    rows = [
        {
            "provider_type": PROVIDER_TYPE_OLLAMA,
            "capability": "embedding",
            "provider_model_ref": fallback_model_version,
            "status": "enabled",
        }
    ]
    ai_hub_model = (AI_HUB_EMBEDDING_MODEL or fallback_model_version).strip()
    ai_hub_enabled = bool(AI_HUB_ENABLED and AI_HUB_BASE_URL.strip() and ai_hub_model)
    rows.append(
        {
            "provider_type": PROVIDER_TYPE_AI_HUB,
            "capability": "embedding",
            "provider_model_ref": ai_hub_model or "unset",
            "status": "enabled" if ai_hub_enabled else "disabled",
        }
    )
    return rows


def _selection_from_registry_row(
    row: Mapping[str, Any],
    *,
    fallback_model_version: str,
) -> EmbeddingProviderSelection:
    provider_key = str(row.get("entity_key") or "").strip()
    provider_model_ref = str(row.get("provider_model_ref") or "").strip()
    if not provider_key:
        raise EmbeddingProviderResolutionError(
            "Active embedding provider row is missing entity_key"
        )
    if not provider_model_ref:
        raise EmbeddingProviderResolutionError(
            "Active embedding provider row is missing provider_model_ref"
        )

    payload = row.get("payload")
    identity = parse_embedding_provider_identity(
        provider_key=provider_key,
        provider_model_ref=provider_model_ref,
        capability=str(row.get("capability") or "").strip() or "embedding",
        payload=payload if isinstance(payload, Mapping) else {},
        fallback_model_version=fallback_model_version,
    )
    if identity.provider_type == PROVIDER_TYPE_AI_HUB:
        _validate_ai_hub_config(required_model_ref=identity.provider_model_ref)

    return EmbeddingProviderSelection(
        provider_type=identity.provider_type,
        provider_key=provider_key,
        capability=identity.capability,
        provider_model_ref=identity.provider_model_ref,
        model_version=identity.model_version,
        provider_config_ref=identity.provider_config_ref,
        model_version_id=_as_optional_str(row.get("model_version_id")),
        embedding_model_version_id=_as_optional_str(row.get("version_id")),
        resolution_source="control_plane_registry_active",
        resolution_reason=None,
    )


def _selection_from_defaults(
    *,
    fallback_model_version: str,
    registry_error: Exception | None,
) -> EmbeddingProviderSelection:
    provider_type = (EMBEDDING_PROVIDER_DEFAULT or PROVIDER_TYPE_OLLAMA).strip().lower()
    reason = (
        f"registry_unavailable:{registry_error}"
        if registry_error is not None
        else "registry_active_embedding_provider_missing"
    )
    if provider_type == PROVIDER_TYPE_AI_HUB:
        _validate_ai_hub_config(required_model_ref=fallback_model_version)
        model_ref = (AI_HUB_EMBEDDING_MODEL or fallback_model_version).strip()
        return EmbeddingProviderSelection(
            provider_type=PROVIDER_TYPE_AI_HUB,
            provider_key="config:ai_hub",
            capability="embedding",
            provider_model_ref=model_ref,
            model_version=model_ref,
            provider_config_ref="env:AI_HUB_*",
            model_version_id=None,
            embedding_model_version_id=None,
            resolution_source="runtime_default_config",
            resolution_reason=reason,
        )

    if provider_type != PROVIDER_TYPE_OLLAMA:
        raise EmbeddingProviderResolutionError(
            "EMBEDDING_PROVIDER_DEFAULT must be 'ollama' or 'ai_hub', got "
            f"{provider_type!r}"
        )

    return EmbeddingProviderSelection(
        provider_type=PROVIDER_TYPE_OLLAMA,
        provider_key="local_ollama",
        capability="embedding",
        provider_model_ref=fallback_model_version,
        model_version=fallback_model_version,
        provider_config_ref=None,
        model_version_id=None,
        embedding_model_version_id=None,
        resolution_source="runtime_default_config",
        resolution_reason=reason,
    )


def _validate_ai_hub_config(*, required_model_ref: str) -> None:
    if not AI_HUB_ENABLED:
        raise EmbeddingProviderResolutionError(
            "AI Hub provider was selected but AI_HUB_ENABLED is false"
        )
    if not AI_HUB_BASE_URL.strip():
        raise EmbeddingProviderResolutionError(
            "AI Hub provider was selected but AI_HUB_BASE_URL is not configured"
        )

    model_ref = (AI_HUB_EMBEDDING_MODEL or required_model_ref).strip()
    if not model_ref:
        raise EmbeddingProviderResolutionError(
            "AI Hub provider was selected but no embedding model was configured"
        )

    has_static_token = bool(AI_HUB_ACCESS_TOKEN.strip())
    has_token_flow = all(
        (
            AI_HUB_TOKEN_URL.strip(),
            AI_HUB_CLIENT_ID.strip(),
            AI_HUB_CLIENT_SECRET.strip(),
            AI_HUB_USERNAME.strip(),
            AI_HUB_PASSWORD.strip(),
        )
    )
    if not has_static_token and not has_token_flow:
        raise EmbeddingProviderResolutionError(
            "AI Hub provider was selected but auth is incomplete. Set either "
            "AI_HUB_ACCESS_TOKEN or token flow fields "
            "(AI_HUB_TOKEN_URL, AI_HUB_CLIENT_ID, AI_HUB_CLIENT_SECRET, "
            "AI_HUB_USERNAME, AI_HUB_PASSWORD)."
        )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None
