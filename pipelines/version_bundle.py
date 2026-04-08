from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Iterable
from uuid import UUID, uuid4

import yaml


@dataclass(frozen=True)
class VersionBundle:
    fs_version: str
    emb_version: str
    model_version: str
    policy_version: str
    index_alias: str
    concrete_qdrant_collection: str
    run_id: str
    campaign_id: str


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            fields.add(field_name)
    return fields


def _require_versions(bundle: VersionBundle) -> None:
    missing = [
        field_name
        for field_name in (
            "fs_version",
            "emb_version",
            "model_version",
            "policy_version",
            "index_alias",
            "concrete_qdrant_collection",
            "run_id",
            "campaign_id",
        )
        if not getattr(bundle, field_name)
    ]
    if missing:
        raise ValueError(f"VersionBundle missing required values: {', '.join(missing)}")

    try:
        UUID(bundle.run_id)
    except ValueError as exc:
        raise ValueError("VersionBundle.run_id must be a valid UUID string") from exc


def build_version_bundle(
    *,
    fs_version: str,
    policy_version: str,
    index_alias: str,
    campaign_id: str,
    embedding_spec_path: Path,
    model_version: str,
) -> VersionBundle:
    emb_spec = _load_yaml(embedding_spec_path)
    prompt_version = emb_spec["template"]["id"]
    run_id = str(uuid4())
    return VersionBundle(
        fs_version=fs_version,
        emb_version=f"{fs_version}+{prompt_version}+{model_version}",
        model_version=model_version,
        policy_version=policy_version,
        index_alias=index_alias,
        concrete_qdrant_collection=f"{index_alias}-{fs_version}-{run_id[:8]}",
        run_id=run_id,
        campaign_id=campaign_id,
    )


def preflight_version_bundle(
    *,
    bundle: VersionBundle,
    embedding_spec_path: Path,
    policy_registry_path: Path,
    feature_registry_path: Path,
    logged_fields: Iterable[str],
    runtime_embedding_model: str | None = None,
    runtime_prompt_version: str | None = None,
) -> None:
    _require_versions(bundle)

    emb_spec = _load_yaml(embedding_spec_path)
    policy_registry = _load_yaml(policy_registry_path)
    feature_registry = _load_yaml(feature_registry_path)

    spec_fs_version = emb_spec.get("composition", {}).get("fs_version")
    if spec_fs_version != bundle.fs_version:
        raise ValueError(
            "Embedding spec fs_version mismatch: "
            f"spec={spec_fs_version!r}, bundle={bundle.fs_version!r}"
        )

    spec_prompt_version = emb_spec.get("composition", {}).get("prompt_version")
    template_prompt_version = emb_spec.get("template", {}).get("id")
    resolved_runtime_prompt_version = runtime_prompt_version or template_prompt_version
    if spec_prompt_version != resolved_runtime_prompt_version:
        raise ValueError(
            "Embedding spec prompt_version mismatch: "
            f"spec={spec_prompt_version!r}, runtime={resolved_runtime_prompt_version!r}"
        )

    resolved_runtime_model = runtime_embedding_model or bundle.model_version
    spec_model_version = emb_spec.get("composition", {}).get("model_version")
    if spec_model_version != resolved_runtime_model:
        raise ValueError(
            "Embedding spec model_version mismatch: "
            f"spec={spec_model_version!r}, runtime={resolved_runtime_model!r}"
        )
    if bundle.model_version != resolved_runtime_model:
        raise ValueError(
            "VersionBundle model_version mismatch: "
            f"bundle={bundle.model_version!r}, runtime={resolved_runtime_model!r}"
        )

    expected_emb_version = (
        f"{bundle.fs_version}+{resolved_runtime_prompt_version}+"
        f"{resolved_runtime_model}"
    )
    if bundle.emb_version != expected_emb_version:
        raise ValueError(
            "VersionBundle emb_version composition mismatch: "
            f"expected={expected_emb_version!r}, bundle={bundle.emb_version!r}"
        )

    policy_versions = {
        p.get("policy_version")
        for p in policy_registry.get("policies", [])
        if p.get("policy_version")
    }
    if bundle.policy_version not in policy_versions:
        raise ValueError(
            f"policy_version not found in policy registry: {bundle.policy_version}"
        )

    feature_meta = {
        feat["id"]: feat
        for feat in feature_registry.get("features", [])
        if feat.get("id")
    }
    embedded_fields = _template_fields(emb_spec["template"]["format"])
    checked_fields = embedded_fields.union(set(logged_fields))
    pii_violations = []
    for field in sorted(checked_fields):
        if field not in feature_meta:
            continue
        pii_tag = str(feature_meta[field].get("pii", "none")).lower()
        if pii_tag != "none":
            pii_violations.append(f"{field} (pii={pii_tag})")

    if pii_violations:
        raise ValueError(
            "PII-tagged fields would be embedded or logged: "
            + ", ".join(pii_violations)
        )
