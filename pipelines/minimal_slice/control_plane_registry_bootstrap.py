from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import EMBEDDING_MODEL_VERSION, FEATURE_SET_PATH, POLICY_VERSION
from .control_plane_registry_service import ControlPlaneRegistryService


@dataclass(frozen=True)
class DevRegistrySeedSpec:
    feature_set_key: str
    fs_version: str
    model_key: str
    model_version: str
    embedding_provider_key: str
    embedding_provider_version: str
    embedding_provider_type: str
    provider_model_ref: str
    provider_config_ref: str | None
    policy_key: str
    policy_version: str
    audience_definition_key: str
    audience_definition_version: str


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return payload if isinstance(payload, dict) else {}


def build_dev_registry_seed_spec() -> DevRegistrySeedSpec:
    feature_set_doc = _read_yaml(FEATURE_SET_PATH)
    fs_version = str(feature_set_doc.get("fs_version") or "fs_credit_v1")
    feature_set_key = str(feature_set_doc.get("feature_set") or fs_version)

    model_version = EMBEDDING_MODEL_VERSION
    model_key = "embedding_model"
    embedding_provider_key = "local_ollama"
    embedding_provider_version = f"emb_provider_{model_version}"
    embedding_provider_type = "ollama"
    provider_model_ref = model_version
    provider_config_ref = None

    policy_version = POLICY_VERSION
    policy_key = (
        policy_version.removesuffix("_v1")
        if policy_version.endswith("_v1")
        else policy_version
    )

    audience_definition_key = "audience_default"
    audience_definition_version = f"{fs_version}__{policy_version}"

    return DevRegistrySeedSpec(
        feature_set_key=feature_set_key,
        fs_version=fs_version,
        model_key=model_key,
        model_version=model_version,
        embedding_provider_key=embedding_provider_key,
        embedding_provider_version=embedding_provider_version,
        embedding_provider_type=embedding_provider_type,
        provider_model_ref=provider_model_ref,
        provider_config_ref=provider_config_ref,
        policy_key=policy_key,
        policy_version=policy_version,
        audience_definition_key=audience_definition_key,
        audience_definition_version=audience_definition_version,
    )


def bootstrap_dev_test_registry(
    *,
    service: ControlPlaneRegistryService | None = None,
    seed_spec: DevRegistrySeedSpec | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    resolved_spec = seed_spec or build_dev_registry_seed_spec()
    result: dict[str, Any] = {
        "bootstrap": "control_plane_registry_dev_test",
        "mode": "dry_run" if dry_run else "apply",
        "seed_spec": asdict(resolved_spec),
        "entities": {},
    }
    if dry_run:
        return result

    runtime_service = service or ControlPlaneRegistryService()

    feature_set_version = runtime_service.ensure_active_version(
        entity_type="feature_sets",
        entity_key=resolved_spec.feature_set_key,
        version=resolved_spec.fs_version,
        metadata={"seeded_by": "bootstrap_dev_test_registry"},
    )
    model_version = runtime_service.ensure_active_version(
        entity_type="models",
        entity_key=resolved_spec.model_key,
        version=resolved_spec.model_version,
        metadata={"seeded_by": "bootstrap_dev_test_registry"},
    )
    provider_version = runtime_service.ensure_active_version(
        entity_type="embedding_providers",
        entity_key=resolved_spec.embedding_provider_key,
        version=resolved_spec.embedding_provider_version,
        metadata={
            "seeded_by": "bootstrap_dev_test_registry",
            "provider_type": resolved_spec.embedding_provider_type,
            "provider_config_ref": resolved_spec.provider_config_ref,
            "model_version": resolved_spec.model_version,
        },
        references={
            "model_version_id": model_version["version_id"],
            "provider_model_ref": resolved_spec.provider_model_ref,
            "capability": "embedding",
        },
    )
    policy_version = runtime_service.ensure_active_version(
        entity_type="policies",
        entity_key=resolved_spec.policy_key,
        version=resolved_spec.policy_version,
        metadata={"seeded_by": "bootstrap_dev_test_registry"},
    )
    audience_definition_version = runtime_service.ensure_active_version(
        entity_type="audience_definitions",
        entity_key=resolved_spec.audience_definition_key,
        version=resolved_spec.audience_definition_version,
        metadata={"seeded_by": "bootstrap_dev_test_registry"},
        references={
            "feature_set_version_id": feature_set_version["version_id"],
            "policy_version_id": policy_version["version_id"],
        },
    )

    result["entities"] = {
        "feature_set_version": feature_set_version,
        "model_version": model_version,
        "embedding_model_version": provider_version,
        "policy_version": policy_version,
        "audience_definition_version": audience_definition_version,
    }
    return result
