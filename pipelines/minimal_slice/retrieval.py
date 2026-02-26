import time
from typing import Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from .config import QDRANT_ALIAS, QDRANT_URL
from .metrics import observe_retrieval_latency

try:
    from langchain_ollama import OllamaEmbeddings
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "langchain-ollama is required. Install dependencies from requirements.txt"
    ) from exc


def retrieve_similar(
    top_k: int = 20,
    query_text: Optional[str] = None,
    query_customer_id: Optional[str] = None,
    ollama_model: str = "nomic-embed-text",
) -> List[Dict]:
    if not query_text and not query_customer_id:
        raise ValueError("Provide either query_text or query_customer_id")

    query_mode = "query_customer_id" if query_customer_id else "query_text"
    start = time.perf_counter()
    try:
        client = QdrantClient(url=QDRANT_URL)
        query_vector = None

        if query_customer_id:
            matches = client.scroll(
                collection_name=QDRANT_ALIAS,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="customer_id", match=MatchValue(value=query_customer_id)
                        )
                    ]
                ),
                with_vectors=True,
                with_payload=False,
                limit=1,
            )[0]
            if not matches:
                raise ValueError(f"customer_id not found in index: {query_customer_id}")
            query_vector = matches[0].vector
        else:
            embedder = OllamaEmbeddings(model=ollama_model)
            query_vector = embedder.embed_query(query_text or "")

        hits = client.search(
            collection_name=QDRANT_ALIAS,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
        )

        results = []
        for h in hits:
            payload = h.payload or {}
            results.append(
                {
                    "customer_id": payload.get("customer_id"),
                    "score": h.score,
                    "payload": payload,
                }
            )
        return results
    finally:
        observe_retrieval_latency(
            query_mode=query_mode,
            duration_seconds=time.perf_counter() - start,
        )
