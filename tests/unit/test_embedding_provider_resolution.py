from __future__ import annotations

import pytest

from pipelines.minimal_slice import embedding_provider_resolution as resolver


def test_resolver_falls_back_to_ollama_when_registry_unavailable(monkeypatch):
    monkeypatch.setattr(
        resolver.control_plane_registry,
        "get_active_version",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable")),
    )
    monkeypatch.setattr(resolver, "EMBEDDING_PROVIDER_DEFAULT", "ollama")

    selected = resolver.resolve_embedding_provider_selection(
        fallback_model_version="nomic-embed-text",
    )

    assert selected.provider_type == "ollama"
    assert selected.provider_model_ref == "nomic-embed-text"
    assert selected.resolution_source == "runtime_default_config"
    assert "registry_unavailable" in str(selected.resolution_reason)


def test_resolver_accepts_registry_ai_hub_provider_when_configured(monkeypatch):
    monkeypatch.setattr(
        resolver.control_plane_registry,
        "get_active_version",
        lambda **kwargs: {
            "version_id": "78de4658-4c27-4835-b29d-f19687093f1d",
            "entity_key": "ai_hub_primary",
            "provider_model_ref": "emb-alpha-v2",
            "capability": "embedding",
            "payload": {
                "provider_type": "ai_hub",
                "model_version": "emb-alpha-v2",
                "provider_config_ref": "ai_hub_prod_main",
            },
        },
    )
    monkeypatch.setattr(resolver, "AI_HUB_ENABLED", True)
    monkeypatch.setattr(resolver, "AI_HUB_BASE_URL", "https://aihub.internal")
    monkeypatch.setattr(resolver, "AI_HUB_EMBEDDING_MODEL", "emb-alpha-v2")
    monkeypatch.setattr(resolver, "AI_HUB_ACCESS_TOKEN", "token")

    selected = resolver.resolve_embedding_provider_selection(
        fallback_model_version="nomic-embed-text",
    )

    assert selected.provider_type == "ai_hub"
    assert selected.provider_model_ref == "emb-alpha-v2"
    assert selected.provider_key == "ai_hub_primary"
    assert selected.resolution_source == "control_plane_registry_active"


def test_resolver_fails_closed_when_registry_selects_ai_hub_without_auth(monkeypatch):
    monkeypatch.setattr(
        resolver.control_plane_registry,
        "get_active_version",
        lambda **kwargs: {
            "version_id": "78de4658-4c27-4835-b29d-f19687093f1d",
            "entity_key": "ai_hub_primary",
            "provider_model_ref": "emb-alpha-v2",
            "capability": "embedding",
            "payload": {
                "provider_type": "ai_hub",
                "model_version": "emb-alpha-v2",
            },
        },
    )
    monkeypatch.setattr(resolver, "EMBEDDING_PROVIDER_DEFAULT", "ollama")
    monkeypatch.setattr(resolver, "AI_HUB_ENABLED", True)
    monkeypatch.setattr(resolver, "AI_HUB_BASE_URL", "https://aihub.internal")
    monkeypatch.setattr(resolver, "AI_HUB_EMBEDDING_MODEL", "emb-alpha-v2")
    monkeypatch.setattr(resolver, "AI_HUB_ACCESS_TOKEN", "")
    monkeypatch.setattr(resolver, "AI_HUB_TOKEN_URL", "")
    monkeypatch.setattr(resolver, "AI_HUB_CLIENT_ID", "")
    monkeypatch.setattr(resolver, "AI_HUB_CLIENT_SECRET", "")
    monkeypatch.setattr(resolver, "AI_HUB_USERNAME", "")
    monkeypatch.setattr(resolver, "AI_HUB_PASSWORD", "")

    with pytest.raises(
        resolver.EmbeddingProviderResolutionError, match="auth is incomplete"
    ):
        resolver.resolve_embedding_provider_selection(
            fallback_model_version="nomic-embed-text",
        )
