from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from pipelines.version_bundle import build_version_bundle, preflight_version_bundle


ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DIR = ROOT / "governance"
EMBEDDING_SPEC_PATH = GOVERNANCE_DIR / "embeddings" / "embedding_specs" / "emb_llm_v1.yaml"
POLICY_REGISTRY_PATH = GOVERNANCE_DIR / "policies" / "policy_registry.yaml"
FEATURE_REGISTRY_PATH = GOVERNANCE_DIR / "features" / "feature_registry.yaml"


def _bundle():
    return build_version_bundle(
        fs_version="fs_credit_v1",
        policy_version="policy_credit_v1",
        index_alias="audience-serving",
        campaign_id="camp_test",
        embedding_spec_path=EMBEDDING_SPEC_PATH,
        model_version="nomic-embed-text",
    )


def test_build_version_bundle_sets_required_fields():
    bundle = _bundle()
    assert bundle.fs_version == "fs_credit_v1"
    assert bundle.policy_version == "policy_credit_v1"
    assert bundle.emb_version == "fs_credit_v1+prompt_credit_v1+nomic-embed-text"
    assert bundle.index_alias == "audience-serving"
    assert bundle.concrete_qdrant_collection.startswith("audience-serving-fs_credit_v1-")
    UUID(bundle.run_id)


def test_preflight_fails_when_version_is_missing():
    bundle = replace(_bundle(), policy_version="")
    with pytest.raises(ValueError, match="missing required values"):
        preflight_version_bundle(
            bundle=bundle,
            embedding_spec_path=EMBEDDING_SPEC_PATH,
            policy_registry_path=POLICY_REGISTRY_PATH,
            feature_registry_path=FEATURE_REGISTRY_PATH,
            logged_fields={"customer_id", "fs_version"},
        )


def test_preflight_fails_when_run_id_is_not_uuid():
    bundle = replace(_bundle(), run_id="not-a-uuid")
    with pytest.raises(ValueError, match="run_id must be a valid UUID"):
        preflight_version_bundle(
            bundle=bundle,
            embedding_spec_path=EMBEDDING_SPEC_PATH,
            policy_registry_path=POLICY_REGISTRY_PATH,
            feature_registry_path=FEATURE_REGISTRY_PATH,
            logged_fields={"customer_id", "fs_version"},
        )


def test_preflight_fails_when_embedding_spec_fs_mismatch(tmp_path: Path):
    broken_spec_path = tmp_path / "embedding_spec.yaml"
    with EMBEDDING_SPEC_PATH.open("r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    spec["composition"]["fs_version"] = "fs_other_v1"
    broken_spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")

    with pytest.raises(ValueError, match="Embedding spec fs_version mismatch"):
        preflight_version_bundle(
            bundle=_bundle(),
            embedding_spec_path=broken_spec_path,
            policy_registry_path=POLICY_REGISTRY_PATH,
            feature_registry_path=FEATURE_REGISTRY_PATH,
            logged_fields={"customer_id", "fs_version"},
        )


def test_preflight_fails_when_policy_not_found():
    bundle = replace(_bundle(), policy_version="policy_missing_v999")
    with pytest.raises(ValueError, match="policy_version not found"):
        preflight_version_bundle(
            bundle=bundle,
            embedding_spec_path=EMBEDDING_SPEC_PATH,
            policy_registry_path=POLICY_REGISTRY_PATH,
            feature_registry_path=FEATURE_REGISTRY_PATH,
            logged_fields={"customer_id", "fs_version"},
        )


def test_preflight_fails_when_pii_field_would_be_embedded(tmp_path: Path):
    broken_spec_path = tmp_path / "embedding_spec_pii.yaml"
    with EMBEDDING_SPEC_PATH.open("r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    spec["template"]["format"] += "\n  first_name={first_name}\n"
    broken_spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")

    with pytest.raises(ValueError, match="PII-tagged fields would be embedded or logged"):
        preflight_version_bundle(
            bundle=_bundle(),
            embedding_spec_path=broken_spec_path,
            policy_registry_path=POLICY_REGISTRY_PATH,
            feature_registry_path=FEATURE_REGISTRY_PATH,
            logged_fields={"customer_id", "fs_version"},
        )
