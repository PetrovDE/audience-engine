from __future__ import annotations

from .ai_hub_embedding_provider import (
    AIHubAuthConfig,
    AIHubEmbeddingClient,
    AIHubEmbeddingConfig,
)
from .config import (
    AI_HUB_ACCESS_TOKEN,
    AI_HUB_BASE_URL,
    AI_HUB_CLIENT_ID,
    AI_HUB_CLIENT_SECRET,
    AI_HUB_EMBEDDING_MODEL,
    AI_HUB_PASSWORD,
    AI_HUB_RETRY_ATTEMPTS,
    AI_HUB_TIMEOUT_SECONDS,
    AI_HUB_TOKEN_URL,
    AI_HUB_USERNAME,
    AI_HUB_VERIFY_SSL,
    OLLAMA_BASE_URL,
)
from .embedding_provider_resolution import (
    EmbeddingProviderResolutionError,
    EmbeddingProviderSelection,
)
from .gpu_guard import ensure_gpu_available
from .provider_identity import PROVIDER_TYPE_AI_HUB, PROVIDER_TYPE_OLLAMA

try:
    from langchain_ollama import OllamaEmbeddings
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "langchain-ollama is required. Install dependencies from requirements.txt"
    ) from exc


def embed_documents_for_selection(
    *,
    texts: list[str],
    selection: EmbeddingProviderSelection,
    gpu_context: str = "Embedding jobs/services",
) -> list[list[float]]:
    if selection.provider_type == PROVIDER_TYPE_OLLAMA:
        ensure_gpu_available(gpu_context)
        embedder = OllamaEmbeddings(
            model=selection.provider_model_ref,
            base_url=OLLAMA_BASE_URL,
        )
        return embedder.embed_documents(texts)

    if selection.provider_type == PROVIDER_TYPE_AI_HUB:
        client = AIHubEmbeddingClient(_build_ai_hub_config(selection))
        return client.embed_documents(texts)

    raise EmbeddingProviderResolutionError(
        f"Unsupported embedding provider_type: {selection.provider_type}"
    )


def embed_query_for_selection(
    *,
    text: str,
    selection: EmbeddingProviderSelection,
    gpu_context: str = "Embedding jobs/services",
) -> list[float]:
    if selection.provider_type == PROVIDER_TYPE_OLLAMA:
        ensure_gpu_available(gpu_context)
        embedder = OllamaEmbeddings(
            model=selection.provider_model_ref,
            base_url=OLLAMA_BASE_URL,
        )
        return embedder.embed_query(text)

    if selection.provider_type == PROVIDER_TYPE_AI_HUB:
        vectors = embed_documents_for_selection(
            texts=[text],
            selection=selection,
            gpu_context=gpu_context,
        )
        return vectors[0]

    raise EmbeddingProviderResolutionError(
        f"Unsupported embedding provider_type: {selection.provider_type}"
    )


def _build_ai_hub_config(selection: EmbeddingProviderSelection) -> AIHubEmbeddingConfig:
    model = (AI_HUB_EMBEDDING_MODEL or selection.provider_model_ref).strip()
    if not model:
        raise EmbeddingProviderResolutionError(
            "AI Hub embedding model is not configured"
        )
    return AIHubEmbeddingConfig(
        base_url=AI_HUB_BASE_URL.strip(),
        model=model,
        timeout_seconds=AI_HUB_TIMEOUT_SECONDS,
        verify_ssl=AI_HUB_VERIFY_SSL,
        retry_attempts=AI_HUB_RETRY_ATTEMPTS,
        auth=AIHubAuthConfig(
            access_token=AI_HUB_ACCESS_TOKEN.strip(),
            token_url=AI_HUB_TOKEN_URL.strip(),
            client_id=AI_HUB_CLIENT_ID.strip(),
            client_secret=AI_HUB_CLIENT_SECRET.strip(),
            username=AI_HUB_USERNAME.strip(),
            password=AI_HUB_PASSWORD.strip(),
            timeout_seconds=AI_HUB_TIMEOUT_SECONDS,
            verify_ssl=AI_HUB_VERIFY_SSL,
            retry_attempts=AI_HUB_RETRY_ATTEMPTS,
        ),
    )

