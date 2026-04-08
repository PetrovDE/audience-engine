from __future__ import annotations

from pathlib import Path
from string import Formatter

import yaml

from pipelines.minimal_slice import config

ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DIR = ROOT / "governance"
FEATURE_REGISTRY_PATH = GOVERNANCE_DIR / "features" / "feature_registry.yaml"
FEATURE_SET_PATH = GOVERNANCE_DIR / "features" / "feature_sets" / "fs_credit_v1.yaml"
EMBEDDING_SPEC_PATH_V1 = (
    GOVERNANCE_DIR / "embeddings" / "embedding_specs" / "emb_llm_v1.yaml"
)
EMBEDDING_SPEC_PATH_V2 = (
    GOVERNANCE_DIR / "embeddings" / "embedding_specs" / "emb_llm_v2.yaml"
)
REASON_CODES_PATH = GOVERNANCE_DIR / "dictionaries" / "reason_codes.yaml"
POLICY_REGISTRY_PATH = GOVERNANCE_DIR / "policies" / "policy_registry.yaml"


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            fields.add(field_name)
    return fields


def test_governance_yaml_has_required_version_fields():
    feature_set = _load_yaml(FEATURE_SET_PATH)
    embedding_spec = _load_yaml(config.EMBED_SPEC_PATH)
    policy_registry = _load_yaml(POLICY_REGISTRY_PATH)

    policy_versions = [
        p.get("policy_version")
        for p in policy_registry.get("policies", [])
        if p.get("policy_version")
    ]
    version_tuple = {
        "fs_version": feature_set.get("fs_version"),
        "emb_version": embedding_spec.get("emb_version"),
        "policy_version": policy_versions[0] if policy_versions else "",
        "index_alias": config.QDRANT_ALIAS,
    }
    missing = [k for k, v in version_tuple.items() if not isinstance(v, str) or not v]
    assert not missing, f"Missing required version tuple fields: {missing}"


def test_policy_registry_reference_paths_resolve():
    policy_registry = _load_yaml(POLICY_REGISTRY_PATH)
    refs = []
    for policy in policy_registry.get("policies", []):
        inputs = policy.get("inputs", {})
        for key in ("raw_contract", "feature_mart_contract", "reason_codes"):
            value = inputs.get(key)
            if value:
                refs.append((policy.get("policy_version", "<unknown>"), key, value))
    assert refs, "No policy input references found in policy registry"

    unresolved = []
    for policy_version, key, rel_path in refs:
        target = ROOT / rel_path
        if not target.exists():
            unresolved.append(f"{policy_version}:{key}:{rel_path}")
    assert not unresolved, f"Unresolved policy registry references: {unresolved}"


def test_feature_set_excludes_pii_and_non_allowlisted_embedding_inputs():
    feature_registry = _load_yaml(FEATURE_REGISTRY_PATH)
    feature_set = _load_yaml(FEATURE_SET_PATH)
    embedding_spec = _load_yaml(config.EMBED_SPEC_PATH)

    feature_meta = {
        item["id"]: item
        for item in feature_registry.get("features", [])
        if item.get("id")
    }
    governed_features = feature_set.get("features", [])
    assert governed_features, "Feature set has no governed features"

    violations = []
    for fid in governed_features:
        meta = feature_meta.get(fid)
        if not meta:
            violations.append(f"{fid}:missing_from_registry")
            continue
        if str(meta.get("pii", "none")).lower() != "none":
            violations.append(f"{fid}:pii={meta.get('pii')}")
        if not bool(meta.get("embedding_allowed", False)):
            violations.append(f"{fid}:embedding_allowed=false")
    assert not violations, (
        "Feature set violates no-PII/allowlist contract: "
        f"{violations}"
    )

    template_fields = _template_fields(embedding_spec["template"]["format"])
    pii_template_fields = []
    for field in sorted(template_fields):
        meta = feature_meta.get(field)
        if not meta:
            continue
        if str(meta.get("pii", "none")).lower() != "none":
            pii_template_fields.append(field)
    assert not pii_template_fields, (
        "Embedding template references PII-tagged fields: "
        + ", ".join(pii_template_fields)
    )


def test_embedding_spec_versioning_is_historically_honest():
    spec_v1 = _load_yaml(EMBEDDING_SPEC_PATH_V1)
    spec_v2 = _load_yaml(EMBEDDING_SPEC_PATH_V2)

    assert spec_v1["version"] == 1
    assert spec_v1["embedding_spec"] == "emb_llm_v1"
    assert spec_v1["composition"]["model_version"] == "text-embedding-3-large"

    assert spec_v2["version"] == 2
    assert spec_v2["embedding_spec"] == "emb_llm_v2"
    assert spec_v2["composition"]["model_version"] == "nomic-embed-text"
    assert spec_v2["composition"]["fs_version"] == spec_v1["composition"]["fs_version"]
    assert spec_v2["composition"]["prompt_version"] == spec_v1["composition"][
        "prompt_version"
    ]

    assert config.EMBED_SPEC_PATH == EMBEDDING_SPEC_PATH_V2


def test_reason_codes_registry_has_versioned_changelog():
    reason_codes = _load_yaml(REASON_CODES_PATH)
    assert int(reason_codes.get("version", 0)) >= 2
    changelog = reason_codes.get("changelog")
    assert isinstance(changelog, list) and changelog, (
        "Reason-code changelog is required"
    )

    codes = {item.get("code") for item in reason_codes.get("codes", [])}
    assert "POLICY_FAIL_CLOSED_REQUIRED_INPUT" in codes
