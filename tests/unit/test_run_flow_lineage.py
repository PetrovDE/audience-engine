from __future__ import annotations

import pytest

pytest.importorskip("psycopg")

from pipelines.minimal_slice import run_flow
from pipelines.version_bundle import VersionBundle


def test_run_flow_fails_when_runtime_embedding_lineage_mismatches_bundle(
    monkeypatch, tmp_path
):
    bundle = VersionBundle(
        fs_version="fs_credit_v1",
        emb_version="fs_credit_v1+prompt_credit_v1+nomic-embed-text",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
        index_alias="audience-serving",
        concrete_qdrant_collection="audience-serving-fs_credit_v1-deadbeef",
        run_id="e0f62885-0dbc-4d53-b1d5-59fd0be558e2",
        campaign_id="camp_test",
    )
    feature_mart_path = tmp_path / "feature_mart.jsonl"
    feature_mart_path.write_text("", encoding="utf-8")
    embeddings_path = tmp_path / "embeddings.jsonl"
    embeddings_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(run_flow, "_build_and_validate_bundle", lambda campaign_id: bundle)
    monkeypatch.setattr(
        run_flow,
        "generate_synthetic_data",
        lambda customer_count, seed: {"raw": tmp_path / "raw.jsonl"},
    )
    monkeypatch.setattr(
        run_flow,
        "build_feature_mart_snapshot",
        lambda raw_path, output_path, source_mode, run_id: feature_mart_path,
    )
    monkeypatch.setattr(
        run_flow,
        "build_embeddings",
        lambda feature_mart_path, ollama_model: (embeddings_path, 8),
    )
    monkeypatch.setattr(
        run_flow,
        "read_embeddings_emb_version",
        lambda path: "fs_credit_v1+prompt_credit_v1+other-model-v2",
    )

    with pytest.raises(ValueError, match="Embedding lineage mismatch at runtime"):
        run_flow.run_minimal_vertical_slice(campaign_id="camp_test")
