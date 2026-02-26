import time
from typing import Dict, List, Optional, Sequence

from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue, Range

from .config import QDRANT_ALIAS, QDRANT_URL
from .gpu_guard import ensure_gpu_available
from .metrics import observe_retrieval_latency

try:
    from langchain_ollama import OllamaEmbeddings
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "langchain-ollama is required. Install dependencies from requirements.txt"
    ) from exc


def _normalize_values(values: Optional[Sequence[str] | str]) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values] if values else []
    return [v for v in values if v]


def _build_ann_filter(
    *,
    product_line: Optional[str] = None,
    region_codes: Optional[Sequence[str] | str] = None,
    segment_ids: Optional[Sequence[str] | str] = None,
    include_employee: bool = False,
    include_do_not_contact: bool = False,
    include_opt_out: bool = False,
    include_legal_suppression: bool = False,
    min_tenure_months: Optional[int] = None,
    max_delinquency_12m_count: Optional[int] = None,
    fs_version: Optional[str] = None,
    emb_version: Optional[str] = None,
    policy_version: Optional[str] = None,
) -> Optional[Filter]:
    must: List[FieldCondition] = []
    if product_line:
        must.append(FieldCondition(key="product_line", match=MatchValue(value=product_line)))
    regions = _normalize_values(region_codes)
    if regions:
        must.append(
            FieldCondition(
                key="region_code",
                match=MatchAny(any=regions),
            )
        )
    segments = _normalize_values(segment_ids)
    if segments:
        must.append(
            FieldCondition(
                key="segment_id",
                match=MatchAny(any=segments),
            )
        )
    if fs_version:
        must.append(FieldCondition(key="fs_version", match=MatchValue(value=fs_version)))
    if emb_version:
        must.append(FieldCondition(key="emb_version", match=MatchValue(value=emb_version)))
    if policy_version:
        must.append(
            FieldCondition(key="policy_version", match=MatchValue(value=policy_version))
        )

    # Keep hard suppressions out of ANN candidates by default.
    if not include_employee:
        must.append(FieldCondition(key="is_employee_flag", match=MatchValue(value=False)))
    if not include_do_not_contact:
        must.append(FieldCondition(key="do_not_contact_flag", match=MatchValue(value=False)))
    if not include_opt_out:
        must.append(FieldCondition(key="opt_out_flag", match=MatchValue(value=False)))
    if not include_legal_suppression:
        must.append(
            FieldCondition(key="legal_suppression_flag", match=MatchValue(value=False))
        )
    if min_tenure_months is not None:
        must.append(
            FieldCondition(
                key="customer_tenure_months",
                range=Range(gte=min_tenure_months),
            )
        )
    if max_delinquency_12m_count is not None:
        must.append(
            FieldCondition(
                key="delinquency_12m_count",
                range=Range(lte=max_delinquency_12m_count),
            )
        )
    return Filter(must=must) if must else None


def retrieve_similar(
    top_k: int = 20,
    query_text: Optional[str] = None,
    query_customer_id: Optional[str] = None,
    ollama_model: str = "nomic-embed-text",
    product_line: Optional[str] = None,
    region_codes: Optional[Sequence[str] | str] = None,
    segment_ids: Optional[Sequence[str] | str] = None,
    include_employee: bool = False,
    include_do_not_contact: bool = False,
    include_opt_out: bool = False,
    include_legal_suppression: bool = False,
    min_tenure_months: Optional[int] = None,
    max_delinquency_12m_count: Optional[int] = None,
    fs_version: Optional[str] = None,
    emb_version: Optional[str] = None,
    policy_version: Optional[str] = None,
) -> List[Dict]:
    if not query_text and not query_customer_id:
        raise ValueError("Provide either query_text or query_customer_id")

    query_mode = "query_customer_id" if query_customer_id else "query_text"
    start = time.perf_counter()
    try:
        client = QdrantClient(url=QDRANT_URL)
        query_vector = None
        ann_filter = _build_ann_filter(
            product_line=product_line,
            region_codes=region_codes,
            segment_ids=segment_ids,
            include_employee=include_employee,
            include_do_not_contact=include_do_not_contact,
            include_opt_out=include_opt_out,
            include_legal_suppression=include_legal_suppression,
            min_tenure_months=min_tenure_months,
            max_delinquency_12m_count=max_delinquency_12m_count,
            fs_version=fs_version,
            emb_version=emb_version,
            policy_version=policy_version,
        )

        if query_customer_id:
            query_point_filter = Filter(
                must=[
                    *(
                        ann_filter.must
                        if ann_filter and ann_filter.must
                        else []
                    ),
                    FieldCondition(
                        key="customer_id", match=MatchValue(value=query_customer_id)
                    ),
                ]
            )
            matches = client.scroll(
                collection_name=QDRANT_ALIAS,
                scroll_filter=query_point_filter,
                with_vectors=True,
                with_payload=False,
                limit=1,
            )[0]
            if not matches:
                raise ValueError(f"customer_id not found in index: {query_customer_id}")
            query_vector = matches[0].vector
        else:
            ensure_gpu_available("Embedding jobs/services")
            embedder = OllamaEmbeddings(model=ollama_model)
            query_vector = embedder.embed_query(query_text or "")

        hits = client.search(
            collection_name=QDRANT_ALIAS,
            query_vector=query_vector,
            query_filter=ann_filter,
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
