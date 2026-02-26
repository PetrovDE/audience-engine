import json
from pathlib import Path
from typing import Dict, List

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    CreateAliasOperation,
    DeleteAliasOperation,
    Distance,
    PointStruct,
    VectorParams,
)

from .config import QDRANT_ALIAS, QDRANT_BLUE_COLLECTION, QDRANT_URL


def _read_jsonl(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _point_id(customer_id: str) -> int:
    return abs(hash(customer_id)) % (2**31 - 1)


def switch_alias_to_blue() -> Dict[str, str]:
    client = QdrantClient(url=QDRANT_URL)
    try:
        client.update_collection_aliases(
            change_aliases_operation=[
                DeleteAliasOperation(delete_alias={"alias_name": QDRANT_ALIAS}),
                CreateAliasOperation(
                    create_alias={
                        "collection_name": QDRANT_BLUE_COLLECTION,
                        "alias_name": QDRANT_ALIAS,
                    }
                ),
            ]
        )
    except Exception:
        client.update_collection_aliases(
            change_aliases_operation=[
                CreateAliasOperation(
                    create_alias={
                        "collection_name": QDRANT_BLUE_COLLECTION,
                        "alias_name": QDRANT_ALIAS,
                    }
                )
            ]
        )
    return {"alias": QDRANT_ALIAS, "collection": QDRANT_BLUE_COLLECTION}


def create_or_replace_index(embeddings_path: Path, vector_size: int) -> Dict[str, str]:
    client = QdrantClient(url=QDRANT_URL)
    points_src = _read_jsonl(embeddings_path)

    client.recreate_collection(
        collection_name=QDRANT_BLUE_COLLECTION,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

    points = []
    for row in points_src:
        payload = {k: v for k, v in row.items() if k != "vector"}
        points.append(
            PointStruct(
                id=_point_id(row["customer_id"]),
                vector=row["vector"],
                payload=payload,
            )
        )
    client.upsert(collection_name=QDRANT_BLUE_COLLECTION, points=points)

    return switch_alias_to_blue()
