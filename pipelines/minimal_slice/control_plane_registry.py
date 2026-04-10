from __future__ import annotations

import argparse
import json
from typing import Any

from .control_plane_registry_bootstrap import (
    DevRegistrySeedSpec,
    bootstrap_dev_test_registry,
    build_dev_registry_seed_spec,
)
from .control_plane_registry_domain import (
    LIFECYCLE_STATES,
    LineagePreconditionError,
    validate_lifecycle_transition,
)
from .control_plane_registry_service import ControlPlaneRegistryService

_service = ControlPlaneRegistryService()


def create_draft_version(
    *,
    entity_type: str,
    entity_key: str,
    version: str,
    metadata: dict[str, Any] | None = None,
    references: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _service.create_draft_version(
        entity_type=entity_type,
        entity_key=entity_key,
        version=version,
        metadata=metadata,
        references=references,
    )


def list_versions(
    *,
    entity_type: str,
    entity_key: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return _service.list_versions(
        entity_type=entity_type,
        entity_key=entity_key,
        limit=limit,
    )


def get_active_version(
    *,
    entity_type: str,
    entity_key: str | None = None,
) -> dict[str, Any] | None:
    return _service.get_active_version(
        entity_type=entity_type,
        entity_key=entity_key,
    )


def transition_version_state(
    *,
    entity_type: str,
    version_id: str,
    target_state: str,
) -> dict[str, Any]:
    return _service.transition_version_state(
        entity_type=entity_type,
        version_id=version_id,
        target_state=target_state,
    )


def resolve_run_lineage_binding(
    *,
    fs_version: str,
    model_version: str,
    policy_version: str,
    feature_set_version_id: str | None = None,
    model_version_id: str | None = None,
    embedding_model_version_id: str | None = None,
    policy_version_id: str | None = None,
    audience_definition_version_id: str | None = None,
) -> dict[str, Any]:
    return _service.resolve_run_lineage_binding(
        fs_version=fs_version,
        model_version=model_version,
        policy_version=policy_version,
        feature_set_version_id=feature_set_version_id,
        model_version_id=model_version_id,
        embedding_model_version_id=embedding_model_version_id,
        policy_version_id=policy_version_id,
        audience_definition_version_id=audience_definition_version_id,
    )


def persist_run_lineage_binding(
    cursor: Any,
    *,
    run_id: str,
    feature_set_version_id: str | None,
    model_version_id: str | None,
    embedding_model_version_id: str | None,
    policy_version_id: str | None,
    audience_definition_version_id: str | None,
    delivery_target_id: str | None,
    export_profile_id: str | None,
) -> None:
    _service.persist_run_lineage_binding(
        cursor,
        run_id=run_id,
        feature_set_version_id=feature_set_version_id,
        model_version_id=model_version_id,
        embedding_model_version_id=embedding_model_version_id,
        policy_version_id=policy_version_id,
        audience_definition_version_id=audience_definition_version_id,
        delivery_target_id=delivery_target_id,
        export_profile_id=export_profile_id,
    )


def bootstrap_registry_for_dev_test(
    *,
    dry_run: bool = False,
    seed_spec: DevRegistrySeedSpec | None = None,
) -> dict[str, Any]:
    return bootstrap_dev_test_registry(
        service=_service,
        seed_spec=seed_spec,
        dry_run=dry_run,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Control-plane registry dev/test bootstrap helper for active default "
            "registry entities."
        )
    )
    parser.add_argument(
        "--bootstrap-dev-test",
        action="store_true",
        help="Seed minimum active control-plane registry entities.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show seed plan without writing to Postgres.",
    )
    parser.add_argument(
        "--show-default-seed-spec",
        action="store_true",
        help="Print resolved default seed spec and exit.",
    )
    args = parser.parse_args()

    if args.show_default_seed_spec:
        print(json.dumps(build_dev_registry_seed_spec().__dict__, indent=2))
        return

    if not args.bootstrap_dev_test:
        parser.error(
            "No action selected. Use --bootstrap-dev-test or "
            "--show-default-seed-spec."
        )

    result = bootstrap_registry_for_dev_test(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()


__all__ = [
    "LIFECYCLE_STATES",
    "LineagePreconditionError",
    "validate_lifecycle_transition",
    "create_draft_version",
    "list_versions",
    "get_active_version",
    "transition_version_state",
    "resolve_run_lineage_binding",
    "persist_run_lineage_binding",
    "bootstrap_registry_for_dev_test",
    "build_dev_registry_seed_spec",
    "DevRegistrySeedSpec",
]
