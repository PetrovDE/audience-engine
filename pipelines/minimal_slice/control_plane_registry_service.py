from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .control_plane_registry_domain import (
    LINEAGE_MODE_DEGRADED,
    LINEAGE_MODE_RESOLVED,
    LineagePreconditionError,
    entity_spec,
    normalize_required,
    validate_lifecycle_transition,
    validate_uuid,
)
from .provider_identity import (
    infer_provider_type_from_key,
    normalize_embedding_capability,
    normalize_provider_type,
)
from .control_plane_registry_lineage_repository import PostgresLineageBindingRepository
from .control_plane_registry_repository import PostgresRegistryRepository

_REQUIRED_LINEAGE_FIELDS = (
    "feature_set_version_id",
    "model_version_id",
    "embedding_model_version_id",
    "policy_version_id",
)


class ControlPlaneRegistryService:
    def __init__(
        self,
        *,
        registry_repo: PostgresRegistryRepository | None = None,
        lineage_repo: PostgresLineageBindingRepository | None = None,
    ) -> None:
        self._registry_repo = registry_repo or PostgresRegistryRepository()
        self._lineage_repo = lineage_repo or PostgresLineageBindingRepository()

    def _normalize_embedding_provider_inputs(
        self,
        *,
        entity_key: str,
        metadata: dict[str, Any],
        references: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        resolved_metadata = dict(metadata)
        resolved_references = dict(references)
        provider_model_ref = normalize_required(
            str(resolved_references.get("provider_model_ref") or ""),
            field="provider_model_ref",
        )
        resolved_references["provider_model_ref"] = provider_model_ref
        resolved_references["capability"] = normalize_embedding_capability(
            str(resolved_references.get("capability") or "embedding"),
        )
        provider_type_raw = str(resolved_metadata.get("provider_type") or "").strip()
        if not provider_type_raw:
            provider_type_raw = str(infer_provider_type_from_key(entity_key) or "")
        resolved_metadata["provider_type"] = normalize_provider_type(
            provider_type_raw,
            field="metadata.provider_type",
        )
        config_ref = str(resolved_metadata.get("provider_config_ref") or "").strip()
        if config_ref:
            resolved_metadata["provider_config_ref"] = config_ref
        else:
            resolved_metadata.pop("provider_config_ref", None)

        model_version = str(resolved_metadata.get("model_version") or "").strip()
        if model_version:
            resolved_metadata["model_version"] = model_version
        return resolved_metadata, resolved_references

    def create_draft_version(
        self,
        *,
        entity_type: str,
        entity_key: str,
        version: str,
        metadata: dict[str, Any] | None = None,
        references: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = entity_spec(entity_type)
        resolved_metadata = metadata if isinstance(metadata, dict) else {}
        resolved_references = references if isinstance(references, dict) else {}
        if entity_type.strip().lower() == "embedding_providers":
            resolved_metadata, resolved_references = (
                self._normalize_embedding_provider_inputs(
                    entity_key=entity_key,
                    metadata=resolved_metadata,
                    references=resolved_references,
                )
            )
        return self._registry_repo.create_draft_version(
            spec=spec,
            entity_key=normalize_required(entity_key, field="entity_key"),
            version=normalize_required(version, field="version"),
            metadata=resolved_metadata,
            references=resolved_references,
        )

    def list_versions(
        self,
        *,
        entity_type: str,
        entity_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return self._registry_repo.list_versions(
            spec=entity_spec(entity_type),
            entity_key=entity_key,
            limit=limit,
        )

    def get_active_version(
        self,
        *,
        entity_type: str,
        entity_key: str | None,
    ) -> dict[str, Any] | None:
        return self._registry_repo.get_active_version(
            spec=entity_spec(entity_type),
            entity_key=entity_key,
        )

    def transition_version_state(
        self,
        *,
        entity_type: str,
        version_id: str,
        target_state: str,
    ) -> dict[str, Any]:
        spec = entity_spec(entity_type)
        resolved_version_id = validate_uuid(version_id, field="version_id")
        resolved_target = normalize_required(target_state, field="target_state").lower()

        current = self._registry_repo.get_version_by_id(
            spec=spec,
            version_id=resolved_version_id,
        )
        if current is None:
            raise ValueError(
                f"Version not found for entity_type={entity_type}: {version_id}"
            )
        validate_lifecycle_transition(current["lifecycle_state"], resolved_target)
        if current["lifecycle_state"] == resolved_target:
            return current

        try:
            updated = self._registry_repo.transition_version_state(
                spec=spec,
                version_id=resolved_version_id,
                target_state=resolved_target,
            )
        except Exception as exc:
            if resolved_target == "active":
                raise ValueError(
                    "Activation failed. Another active version may already exist "
                    "for this entity."
                ) from exc
            raise

        if updated is None:
            raise RuntimeError("Version disappeared after lifecycle transition update")
        return updated

    def _lineage_degraded_payload(
        self,
        *,
        resolved: dict[str, str | None],
        reasons: list[str],
        explicit_requested: bool,
    ) -> dict[str, Any]:
        return {
            **resolved,
            "lineage_resolution_mode": LINEAGE_MODE_DEGRADED,
            "lineage_resolution_reasons": reasons,
            "lineage_resolution_timestamp": datetime.now(timezone.utc).isoformat(),
            "lineage_resolution_strict_expected": explicit_requested,
            "lineage_resolution_degraded": True,
        }

    def resolve_run_lineage_binding(
        self,
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
        explicit_requested = any(
            (
                feature_set_version_id,
                model_version_id,
                embedding_model_version_id,
                policy_version_id,
                audience_definition_version_id,
            )
        )
        try:
            resolved = self._lineage_repo.resolve_run_lineage_ids(
                fs_version=fs_version,
                model_version=model_version,
                policy_version=policy_version,
                feature_set_version_id=feature_set_version_id,
                model_version_id=model_version_id,
                embedding_model_version_id=embedding_model_version_id,
                policy_version_id=policy_version_id,
                audience_definition_version_id=audience_definition_version_id,
            )
        except Exception as exc:
            if explicit_requested:
                raise LineagePreconditionError(
                    "Registry lineage precondition failed while resolving explicit "
                    "version identifiers. Check registry connectivity and provided "
                    "*_version_id values."
                ) from exc
            return self._lineage_degraded_payload(
                resolved={
                    "feature_set_version_id": None,
                    "model_version_id": None,
                    "embedding_model_version_id": None,
                    "policy_version_id": None,
                    "audience_definition_version_id": None,
                    "embedding_provider_id": None,
                    "embedding_provider_key": None,
                    "provider_type": None,
                    "provider_model_ref": None,
                    "capability": None,
                },
                reasons=[f"registry_unavailable:{exc}"],
                explicit_requested=False,
            )

        missing_required = [
            field for field in _REQUIRED_LINEAGE_FIELDS if not resolved.get(field)
        ]
        missing_optional = [
            "audience_definition_version_id"
            if not resolved.get("audience_definition_version_id")
            else ""
        ]
        missing_optional = [value for value in missing_optional if value]

        if missing_required:
            details = ", ".join(missing_required)
            if explicit_requested:
                raise LineagePreconditionError(
                    "Registry lineage precondition failed: missing active version ids "
                    f"for [{details}]. Run dev/test registry bootstrap or provide "
                    "explicit active *_version_id values."
                )
            reasons = [f"missing_required_active_versions:{details}"]
            if missing_optional:
                reasons.append(
                    "missing_optional_active_versions:"
                    + ",".join(sorted(missing_optional))
                )
            return self._lineage_degraded_payload(
                resolved=resolved,
                reasons=reasons,
                explicit_requested=False,
            )

        response: dict[str, Any] = {
            **resolved,
            "lineage_resolution_mode": LINEAGE_MODE_RESOLVED,
            "lineage_resolution_reasons": [],
            "lineage_resolution_timestamp": datetime.now(timezone.utc).isoformat(),
            "lineage_resolution_strict_expected": explicit_requested,
            "lineage_resolution_degraded": False,
        }
        if missing_optional:
            response["lineage_resolution_reasons"] = [
                "missing_optional_active_versions:" + ",".join(sorted(missing_optional))
            ]
        return response

    def persist_run_lineage_binding(self, cursor: Any, **kwargs: Any) -> None:
        self._lineage_repo.persist_run_lineage_binding(cursor, **kwargs)

    def ensure_active_version(
        self,
        *,
        entity_type: str,
        entity_key: str,
        version: str,
        metadata: dict[str, Any] | None = None,
        references: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = entity_spec(entity_type)
        resolved_key = normalize_required(entity_key, field="entity_key")
        resolved_version = normalize_required(version, field="version")

        row = self._registry_repo.find_version(
            spec=spec,
            entity_key=resolved_key,
            version=resolved_version,
        )
        if row is None:
            row = self.create_draft_version(
                entity_type=entity_type,
                entity_key=resolved_key,
                version=resolved_version,
                metadata=metadata,
                references=references,
            )

        state = str(row["lifecycle_state"])
        while state != "active":
            if state == "draft":
                target = "validated"
            elif state in {"validated", "deprecated"}:
                current_active = self.get_active_version(
                    entity_type=entity_type,
                    entity_key=resolved_key,
                )
                if (
                    current_active is not None
                    and str(current_active["version_id"]) != str(row["version_id"])
                ):
                    self.transition_version_state(
                        entity_type=entity_type,
                        version_id=str(current_active["version_id"]),
                        target_state="deprecated",
                    )
                target = "active"
            else:
                raise ValueError(
                    "Cannot auto-activate "
                    f"{entity_type}:{resolved_key}:{resolved_version} "
                    f"from lifecycle_state={state}"
                )
            row = self.transition_version_state(
                entity_type=entity_type,
                version_id=str(row["version_id"]),
                target_state=target,
            )
            state = str(row["lifecycle_state"])

        return row
