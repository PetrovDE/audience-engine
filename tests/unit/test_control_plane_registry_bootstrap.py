from __future__ import annotations

from pipelines.minimal_slice.control_plane_registry_bootstrap import (
    DevRegistrySeedSpec,
    bootstrap_dev_test_registry,
)


class _FakeRegistryService:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def ensure_active_version(self, **kwargs):
        self.calls.append((kwargs["entity_type"], kwargs))
        version_id = {
            "feature_sets": "d4295d8f-c391-4730-b827-5e92f74fdc27",
            "models": "7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79",
            "embedding_providers": "78de4658-4c27-4835-b29d-f19687093f1d",
            "policies": "7f3029bd-0eb9-4d81-a0f3-88202523fca6",
            "audience_definitions": "8ac37deb-4e2d-45d7-bbe4-1846a9027dc1",
        }[kwargs["entity_type"]]
        return {
            "version_id": version_id,
            "entity_key": kwargs["entity_key"],
            "version": kwargs["version"],
            "lifecycle_state": "active",
            "payload": kwargs.get("metadata", {}),
        }


def _seed_spec() -> DevRegistrySeedSpec:
    return DevRegistrySeedSpec(
        feature_set_key="fs_credit",
        fs_version="fs_credit_v1",
        model_key="embedding_model",
        model_version="nomic-embed-text",
        embedding_provider_key="local_ollama",
        embedding_provider_version="emb_provider_nomic-embed-text",
        embedding_provider_type="ollama",
        provider_model_ref="nomic-embed-text",
        provider_config_ref=None,
        policy_key="policy_credit",
        policy_version="policy_credit_v1",
        audience_definition_key="audience_default",
        audience_definition_version="fs_credit_v1__policy_credit_v1",
    )


def test_bootstrap_dev_test_registry_dry_run_is_explicit_and_non_mutating():
    payload = bootstrap_dev_test_registry(
        service=_FakeRegistryService(),
        seed_spec=_seed_spec(),
        dry_run=True,
    )

    assert payload["mode"] == "dry_run"
    assert payload["entities"] == {}
    assert payload["seed_spec"]["fs_version"] == "fs_credit_v1"


def test_bootstrap_dev_test_registry_seeds_minimum_active_entities_with_references():
    service = _FakeRegistryService()

    payload = bootstrap_dev_test_registry(
        service=service,
        seed_spec=_seed_spec(),
        dry_run=False,
    )

    call_order = [entity_type for entity_type, _ in service.calls]
    assert call_order == [
        "feature_sets",
        "models",
        "embedding_providers",
        "policies",
        "audience_definitions",
    ]

    provider_call = service.calls[2][1]
    assert (
        provider_call["references"]["model_version_id"]
        == "7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79"
    )
    assert provider_call["references"]["provider_model_ref"] == "nomic-embed-text"
    assert provider_call["metadata"]["provider_type"] == "ollama"
    assert provider_call["metadata"]["model_version"] == "nomic-embed-text"

    audience_call = service.calls[4][1]
    assert (
        audience_call["references"]["feature_set_version_id"]
        == "d4295d8f-c391-4730-b827-5e92f74fdc27"
    )
    assert (
        audience_call["references"]["policy_version_id"]
        == "7f3029bd-0eb9-4d81-a0f3-88202523fca6"
    )

    assert payload["mode"] == "apply"
    assert payload["entities"]["feature_set_version"]["lifecycle_state"] == "active"
    assert (
        payload["entities"]["audience_definition_version"]["lifecycle_state"]
        == "active"
    )
