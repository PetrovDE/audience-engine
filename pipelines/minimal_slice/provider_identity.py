from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PROVIDER_TYPE_OLLAMA = "ollama"
PROVIDER_TYPE_AI_HUB = "ai_hub"
EMBEDDING_CAPABILITY = "embedding"

_SUPPORTED_PROVIDER_TYPES = {
    PROVIDER_TYPE_OLLAMA,
    PROVIDER_TYPE_AI_HUB,
}


@dataclass(frozen=True)
class EmbeddingProviderIdentity:
    provider_type: str
    provider_model_ref: str
    capability: str
    model_version: str
    provider_config_ref: str | None


def normalize_provider_type(value: str, *, field: str = "provider_type") -> str:
    resolved = value.strip().lower()
    if not resolved:
        raise ValueError(f"{field} is required")
    if resolved not in _SUPPORTED_PROVIDER_TYPES:
        supported = ", ".join(sorted(_SUPPORTED_PROVIDER_TYPES))
        raise ValueError(f"{field} must be one of [{supported}], got {value!r}")
    return resolved


def normalize_embedding_capability(
    value: str | None,
    *,
    field: str = "capability",
) -> str:
    resolved = str(value or EMBEDDING_CAPABILITY).strip().lower()
    if resolved != EMBEDDING_CAPABILITY:
        raise ValueError(
            f"{field} must be {EMBEDDING_CAPABILITY!r} for embedding provider wiring"
        )
    return resolved


def infer_provider_type_from_key(provider_key: str | None) -> str | None:
    key = str(provider_key or "").strip().lower()
    if not key:
        return None
    if "ollama" in key or key.startswith("local_"):
        return PROVIDER_TYPE_OLLAMA
    if "ai_hub" in key or "aihub" in key:
        return PROVIDER_TYPE_AI_HUB
    return None


def parse_embedding_provider_identity(
    *,
    provider_key: str,
    provider_model_ref: str,
    capability: str | None,
    payload: Mapping[str, Any] | None,
    fallback_model_version: str,
) -> EmbeddingProviderIdentity:
    metadata = payload if isinstance(payload, Mapping) else {}
    provider_model = provider_model_ref.strip()
    if not provider_model:
        raise ValueError("provider_model_ref is required")
    declared_type = str(metadata.get("provider_type") or "").strip()
    inferred_type = infer_provider_type_from_key(provider_key)
    provider_type = (
        normalize_provider_type(declared_type, field="payload.provider_type")
        if declared_type
        else normalize_provider_type(
            inferred_type or PROVIDER_TYPE_OLLAMA,
            field="inferred_provider_type",
        )
    )
    capability_value = normalize_embedding_capability(capability)
    model_version = str(metadata.get("model_version") or fallback_model_version).strip()
    if not model_version:
        raise ValueError("model_version is required in payload or runtime fallback")
    config_ref_raw = str(metadata.get("provider_config_ref") or "").strip()
    return EmbeddingProviderIdentity(
        provider_type=provider_type,
        provider_model_ref=provider_model,
        capability=capability_value,
        model_version=model_version,
        provider_config_ref=config_ref_raw or None,
    )
