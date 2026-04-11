from __future__ import annotations

import pytest

from pipelines.minimal_slice.control_plane_registry_domain import (
    LineagePreconditionError,
)
from pipelines.minimal_slice.control_plane_registry_service import (
    ControlPlaneRegistryService,
)


class _StubRegistryRepo:
    def __init__(self):
        self.transition_calls = []
        self.create_calls = []

    def create_draft_version(
        self,
        *,
        spec,
        entity_key,
        version,
        metadata,
        references,
    ):
        self.create_calls.append(
            {
                "spec": spec,
                "entity_key": entity_key,
                "version": version,
                "metadata": metadata,
                "references": references,
            }
        )
        return {
            "version_id": "c4c5f52d-ec77-4fa8-8963-03de9ad89866",
            "entity_key": entity_key,
            "version": version,
            "lifecycle_state": "draft",
            "payload": metadata,
            **references,
        }

    def get_version_by_id(self, *, spec, version_id):
        return {
            "version_id": version_id,
            "entity_key": "fs_credit",
            "version": "fs_credit_v1",
            "lifecycle_state": "validated",
            "payload": {},
        }

    def transition_version_state(self, *, spec, version_id, target_state):
        self.transition_calls.append((version_id, target_state))
        return {
            "version_id": version_id,
            "entity_key": "fs_credit",
            "version": "fs_credit_v1",
            "lifecycle_state": target_state,
            "payload": {},
        }


class _DraftStateRegistryRepo(_StubRegistryRepo):
    def get_version_by_id(self, *, spec, version_id):
        payload = super().get_version_by_id(spec=spec, version_id=version_id)
        payload["lifecycle_state"] = "draft"
        return payload


class _StubLineageRepo:
    def __init__(self, result=None, exc: Exception | None = None):
        self._result = result
        self._exc = exc

    def resolve_run_lineage_ids(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.fixture
def resolved_lineage_ids() -> dict[str, str]:
    return {
        "feature_set_version_id": "d4295d8f-c391-4730-b827-5e92f74fdc27",
        "model_version_id": "7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79",
        "embedding_model_version_id": "78de4658-4c27-4835-b29d-f19687093f1d",
        "policy_version_id": "7f3029bd-0eb9-4d81-a0f3-88202523fca6",
        "audience_definition_version_id": "8ac37deb-4e2d-45d7-bbe4-1846a9027dc1",
        "embedding_provider_id": "10a4cd6e-9db0-4ecf-a599-8c051df363a7",
        "embedding_provider_key": "local_ollama",
        "provider_type": "ollama",
        "provider_model_ref": "nomic-embed-text",
        "capability": "embedding",
    }


def test_lineage_resolves_to_versioned_mode_when_all_required_ids_present(
    resolved_lineage_ids,
):
    service = ControlPlaneRegistryService(
        registry_repo=_StubRegistryRepo(),
        lineage_repo=_StubLineageRepo(result=resolved_lineage_ids),
    )

    lineage = service.resolve_run_lineage_binding(
        fs_version="fs_credit_v1",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
    )

    assert lineage["lineage_resolution_mode"] == "resolved_versioned"
    assert lineage["lineage_resolution_degraded"] is False
    assert lineage["lineage_resolution_reasons"] == []
    assert (
        lineage["feature_set_version_id"]
        == resolved_lineage_ids["feature_set_version_id"]
    )
    assert lineage["provider_type"] == "ollama"
    assert lineage["provider_model_ref"] == "nomic-embed-text"


def test_lineage_marks_degraded_unversioned_when_required_active_ids_missing(
    resolved_lineage_ids,
):
    missing = dict(resolved_lineage_ids)
    missing["feature_set_version_id"] = None
    missing["model_version_id"] = None

    service = ControlPlaneRegistryService(
        registry_repo=_StubRegistryRepo(),
        lineage_repo=_StubLineageRepo(result=missing),
    )

    lineage = service.resolve_run_lineage_binding(
        fs_version="fs_credit_v1",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
    )

    assert lineage["lineage_resolution_mode"] == "degraded_unversioned"
    assert lineage["lineage_resolution_degraded"] is True
    reasons = " ".join(lineage["lineage_resolution_reasons"])
    assert "missing_required_active_versions" in reasons
    assert "feature_set_version_id" in reasons
    assert "model_version_id" in reasons


def test_lineage_precondition_fails_when_strict_explicit_mode_has_missing_required_ids(
    resolved_lineage_ids,
):
    missing = dict(resolved_lineage_ids)
    missing["embedding_model_version_id"] = None

    service = ControlPlaneRegistryService(
        registry_repo=_StubRegistryRepo(),
        lineage_repo=_StubLineageRepo(result=missing),
    )

    with pytest.raises(LineagePreconditionError, match="missing active version ids"):
        service.resolve_run_lineage_binding(
            fs_version="fs_credit_v1",
            model_version="nomic-embed-text",
            policy_version="policy_credit_v1",
            feature_set_version_id=resolved_lineage_ids["feature_set_version_id"],
        )


def test_lineage_degrades_with_explicit_reason_when_registry_unavailable_non_strict():
    service = ControlPlaneRegistryService(
        registry_repo=_StubRegistryRepo(),
        lineage_repo=_StubLineageRepo(exc=RuntimeError("db timeout")),
    )

    lineage = service.resolve_run_lineage_binding(
        fs_version="fs_credit_v1",
        model_version="nomic-embed-text",
        policy_version="policy_credit_v1",
    )

    assert lineage["lineage_resolution_mode"] == "degraded_unversioned"
    assert lineage["lineage_resolution_degraded"] is True
    assert "registry_unavailable" in lineage["lineage_resolution_reasons"][0]


def test_transition_state_enforced_in_service_layer():
    repo = _StubRegistryRepo()
    service = ControlPlaneRegistryService(
        registry_repo=repo,
        lineage_repo=_StubLineageRepo(result={}),
    )

    updated = service.transition_version_state(
        entity_type="feature_sets",
        version_id="d4295d8f-c391-4730-b827-5e92f74fdc27",
        target_state="active",
    )

    assert updated["lifecycle_state"] == "active"
    assert repo.transition_calls == [
        ("d4295d8f-c391-4730-b827-5e92f74fdc27", "active")
    ]


def test_transition_rejects_invalid_state_edge_in_service_layer():
    repo = _DraftStateRegistryRepo()
    service = ControlPlaneRegistryService(
        registry_repo=repo,
        lineage_repo=_StubLineageRepo(result={}),
    )

    with pytest.raises(ValueError, match="Invalid lifecycle transition"):
        service.transition_version_state(
            entity_type="feature_sets",
            version_id="d4295d8f-c391-4730-b827-5e92f74fdc27",
            target_state="active",
        )

    assert repo.transition_calls == []


def test_create_draft_embedding_provider_normalizes_provider_identity():
    repo = _StubRegistryRepo()
    service = ControlPlaneRegistryService(
        registry_repo=repo,
        lineage_repo=_StubLineageRepo(result={}),
    )

    row = service.create_draft_version(
        entity_type="embedding_providers",
        entity_key="local_ollama",
        version="emb_provider_nomic",
        metadata={"model_version": "nomic-embed-text"},
        references={
            "model_version_id": "7e8ce4be-a6fd-4fe5-a85a-3c5f903fce79",
            "provider_model_ref": "nomic-embed-text",
        },
    )

    assert row["provider_model_ref"] == "nomic-embed-text"
    assert row["capability"] == "embedding"
    assert repo.create_calls[0]["metadata"]["provider_type"] == "ollama"
