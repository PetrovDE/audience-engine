from __future__ import annotations

import json

import pytest

from pipelines.minimal_slice.embedding import read_embeddings_emb_version


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_read_embeddings_emb_version_accepts_uniform_artifact(tmp_path):
    embeddings_path = tmp_path / "embeddings.jsonl"
    _write_jsonl(
        embeddings_path,
        [
            {"customer_id": "cust_1", "emb_version": "emb_vx", "vector": [0.1, 0.2]},
            {"customer_id": "cust_2", "emb_version": "emb_vx", "vector": [0.3, 0.4]},
        ],
    )

    assert read_embeddings_emb_version(embeddings_path) == "emb_vx"


def test_read_embeddings_emb_version_fails_on_missing_emb_version(tmp_path):
    embeddings_path = tmp_path / "embeddings_missing.jsonl"
    _write_jsonl(
        embeddings_path,
        [
            {"customer_id": "cust_1", "emb_version": "emb_vx"},
            {"customer_id": "cust_2"},
        ],
    )

    with pytest.raises(ValueError, match="missing emb_version"):
        read_embeddings_emb_version(embeddings_path)


def test_read_embeddings_emb_version_fails_on_mixed_versions(tmp_path):
    embeddings_path = tmp_path / "embeddings_mixed.jsonl"
    _write_jsonl(
        embeddings_path,
        [
            {"customer_id": "cust_1", "emb_version": "emb_vx"},
            {"customer_id": "cust_2", "emb_version": "emb_vy"},
        ],
    )

    with pytest.raises(ValueError, match="mixed emb_version"):
        read_embeddings_emb_version(embeddings_path)

