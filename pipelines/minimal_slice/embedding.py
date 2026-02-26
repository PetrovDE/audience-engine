import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from .config import EMBEDDINGS_PATH, EMBED_SPEC_PATH
from .gpu_guard import ensure_gpu_available
from .metrics import record_embedding_batch
from .storage import get_cached_embedding, set_cached_embedding

try:
    from langchain_ollama import OllamaEmbeddings
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "langchain-ollama is required. Install dependencies from requirements.txt"
    ) from exc


def _read_jsonl(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _render_template(template: str, row: Dict) -> str:
    return template.format(**row)


def build_embeddings(
    feature_mart_path: Path,
    output_path: Path = EMBEDDINGS_PATH,
    ollama_model: str = "nomic-embed-text",
) -> Tuple[Path, int]:
    ensure_gpu_available("Embedding jobs/services")

    with EMBED_SPEC_PATH.open("r", encoding="utf-8") as f:
        emb_spec = yaml.safe_load(f)

    template = emb_spec["template"]["format"]
    prompt_version = emb_spec["template"]["id"]
    rows = _read_jsonl(feature_mart_path)
    docs = [_render_template(template, row) for row in rows]
    fs_version = str(rows[0]["fs_version"]) if rows else "unknown"
    emb_version = f"{fs_version}+{prompt_version}+{ollama_model}"

    embedder = OllamaEmbeddings(model=ollama_model)
    start = time.perf_counter()
    vectors: List[List[float]] = []
    missing_docs: List[str] = []
    missing_positions: List[int] = []
    for idx, text in enumerate(docs):
        cached = get_cached_embedding(emb_version=emb_version, text=text)
        if cached is None:
            vectors.append([])
            missing_docs.append(text)
            missing_positions.append(idx)
            continue
        vectors.append(cached)

    if missing_docs:
        generated = embedder.embed_documents(missing_docs)
        for pos, text, vector in zip(missing_positions, missing_docs, generated):
            vectors[pos] = vector
            set_cached_embedding(emb_version=emb_version, text=text, vector=vector)

    duration_seconds = time.perf_counter() - start
    record_embedding_batch(
        model=ollama_model,
        doc_count=len(docs),
        duration_seconds=duration_seconds,
    )
    dim = len(vectors[0]) if vectors else 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row, text, vector in zip(rows, docs, vectors):
            payload = {
                "customer_id": row["customer_id"],
                "fs_version": row["fs_version"],
                "emb_version": emb_version,
                "policy_version": row["policy_version"],
                "embedding_text": text,
                "vector": vector,
                "is_employee_flag": row["is_employee_flag"],
                "do_not_contact_flag": row["do_not_contact_flag"],
                "opt_out_flag": row.get("opt_out_flag", False),
                "legal_suppression_flag": row.get("legal_suppression_flag", False),
                "customer_tenure_months": row["customer_tenure_months"],
                "delinquency_12m_count": row["delinquency_12m_count"],
                "region_code": row.get("region_code", "unknown"),
                "segment_id": row.get("segment_id", "unknown"),
                "product_line": row.get("product_line", "unknown"),
            }
            f.write(json.dumps(payload) + "\n")
    return output_path, dim
