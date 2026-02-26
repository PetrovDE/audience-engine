import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from .config import EMBEDDINGS_PATH, EMBED_SPEC_PATH
from .metrics import record_embedding_batch

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
    with EMBED_SPEC_PATH.open("r", encoding="utf-8") as f:
        emb_spec = yaml.safe_load(f)

    template = emb_spec["template"]["format"]
    prompt_version = emb_spec["template"]["id"]
    rows = _read_jsonl(feature_mart_path)
    docs = [_render_template(template, row) for row in rows]

    embedder = OllamaEmbeddings(model=ollama_model)
    start = time.perf_counter()
    vectors = embedder.embed_documents(docs)
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
                "emb_version": f"{row['fs_version']}+{prompt_version}+{ollama_model}",
                "policy_version": row["policy_version"],
                "embedding_text": text,
                "vector": vector,
                "is_employee_flag": row["is_employee_flag"],
                "do_not_contact_flag": row["do_not_contact_flag"],
                "customer_tenure_months": row["customer_tenure_months"],
                "delinquency_12m_count": row["delinquency_12m_count"],
            }
            f.write(json.dumps(payload) + "\n")
    return output_path, dim
