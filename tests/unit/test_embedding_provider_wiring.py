from __future__ import annotations

import json

from pipelines.minimal_slice import embedding
from pipelines.minimal_slice.embedding_provider_resolution import (
    EmbeddingProviderSelection,
)


def test_build_embeddings_records_provider_identity(monkeypatch, tmp_path):
    feature_mart_path = tmp_path / "feature_mart.jsonl"
    feature_mart_path.write_text(
        json.dumps(
            {
                "customer_id": "cust_1",
                "fs_version": "fs_credit_v1",
                "policy_version": "policy_credit_v1",
                "is_employee_flag": False,
                "do_not_contact_flag": False,
                "opt_out_flag": False,
                "legal_suppression_flag": False,
                "customer_tenure_months": 12,
                "delinquency_12m_count": 0,
                "region_code": "us_west",
                "segment_id": "mass",
                "product_line": "credit_card",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    emb_spec_path = tmp_path / "embedding_spec.yaml"
    emb_spec_path.write_text(
        (
            "template:\n"
            "  id: prompt_credit_v1\n"
            "  format: \"customer {customer_id}\"\n"
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "embeddings.jsonl"

    monkeypatch.setattr(embedding, "EMBED_SPEC_PATH", emb_spec_path)
    monkeypatch.setattr(
        embedding,
        "resolve_embedding_provider_selection",
        lambda fallback_model_version: EmbeddingProviderSelection(
            provider_type="ollama",
            provider_key="local_ollama",
            capability="embedding",
            provider_model_ref="nomic-embed-text",
            model_version="nomic-embed-text",
            provider_config_ref=None,
            model_version_id="7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79",
            embedding_model_version_id="78de4658-4c27-4835-b29d-f19687093f1d",
            resolution_source="runtime_default_config",
            resolution_reason="registry_unavailable",
        ),
    )
    monkeypatch.setattr(
        embedding,
        "embed_documents_for_selection",
        lambda texts, selection, gpu_context: [[0.1, 0.2] for _ in texts],
    )
    monkeypatch.setattr(embedding, "get_cached_embedding", lambda **kwargs: None)
    monkeypatch.setattr(embedding, "set_cached_embedding", lambda **kwargs: None)
    monkeypatch.setattr(embedding, "record_embedding_batch", lambda **kwargs: None)

    generated_path, vector_size = embedding.build_embeddings(
        feature_mart_path=feature_mart_path,
        output_path=output_path,
        ollama_model="nomic-embed-text",
    )

    assert generated_path == output_path
    assert vector_size == 2
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["embedding_provider_type"] == "ollama"
    assert rows[0]["embedding_provider_key"] == "local_ollama"
    assert rows[0]["embedding_provider_model_ref"] == "nomic-embed-text"
    assert rows[0]["embedding_model_version"] == "nomic-embed-text"
