import json
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field

from pipelines.minimal_slice.config import SUMMARY_PATH
from pipelines.minimal_slice.retrieval import retrieve_similar
from pipelines.version_bundle import VersionBundle

app = FastAPI(title="Audience Engine Retrieval API", version="0.1.0")
app.mount("/metrics", make_asgi_app())


class RetrieveRequest(BaseModel):
    top_k: int = Field(default=20, ge=1, le=200)
    query_text: Optional[str] = None
    query_customer_id: Optional[str] = None
    product_line: Optional[str] = None
    region_codes: Optional[List[str]] = None
    segment_ids: Optional[List[str]] = None
    include_employee: bool = False
    include_do_not_contact: bool = False
    include_opt_out: bool = False
    include_legal_suppression: bool = False
    min_tenure_months: Optional[int] = Field(default=None, ge=0)
    max_delinquency_12m_count: Optional[int] = Field(default=None, ge=0)
    fs_version: Optional[str] = None
    emb_version: Optional[str] = None
    policy_version: Optional[str] = None


@app.get("/healthz")
def healthz() -> dict:
    bundle = _load_latest_version_bundle()
    return {"status": "ok", "version_bundle": bundle.__dict__ if bundle else None}


def _load_latest_version_bundle() -> Optional[VersionBundle]:
    if not SUMMARY_PATH.exists():
        return None
    with SUMMARY_PATH.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    versions = summary.get("versions")
    if not isinstance(versions, dict):
        return None
    try:
        return VersionBundle(**versions)
    except TypeError:
        return None


@app.post("/v1/retrieve")
def retrieve(request: RetrieveRequest) -> dict:
    if not request.query_text and not request.query_customer_id:
        raise HTTPException(
            status_code=400, detail="Provide query_text or query_customer_id"
        )

    try:
        rows = retrieve_similar(
            top_k=request.top_k,
            query_text=request.query_text,
            query_customer_id=request.query_customer_id,
            product_line=request.product_line,
            region_codes=request.region_codes,
            segment_ids=request.segment_ids,
            include_employee=request.include_employee,
            include_do_not_contact=request.include_do_not_contact,
            include_opt_out=request.include_opt_out,
            include_legal_suppression=request.include_legal_suppression,
            min_tenure_months=request.min_tenure_months,
            max_delinquency_12m_count=request.max_delinquency_12m_count,
            fs_version=request.fs_version,
            emb_version=request.emb_version,
            policy_version=request.policy_version,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"count": len(rows), "results": rows}
