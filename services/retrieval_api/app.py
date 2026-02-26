from typing import Optional

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field

from pipelines.minimal_slice.retrieval import retrieve_similar

app = FastAPI(title="Audience Engine Retrieval API", version="0.1.0")
app.mount("/metrics", make_asgi_app())


class RetrieveRequest(BaseModel):
    top_k: int = Field(default=20, ge=1, le=200)
    query_text: Optional[str] = None
    query_customer_id: Optional[str] = None


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


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
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"count": len(rows), "results": rows}
