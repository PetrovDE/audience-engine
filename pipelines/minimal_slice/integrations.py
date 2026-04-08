from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import EXPORT_PATH, FEATURE_MART_PATH
from .control_plane import get_integration_profile
from .exporter import export_approved
from .feature_mart import build_feature_mart_snapshot
from .storage import minio_is_configured, upload_export_to_minio


class SourceConnector(Protocol):
    connector_id: str

    def build_feature_mart(
        self,
        *,
        raw_path: Path,
        output_path: Path,
        run_id: str,
    ) -> Path: ...


class ExportTarget(Protocol):
    target_id: str

    def export(
        self,
        *,
        policy_result: dict[str, Any],
        output_path: Path,
        run_id: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SnapshotSourceConnector:
    connector_id: str = "snapshot_jsonl"

    def build_feature_mart(
        self,
        *,
        raw_path: Path,
        output_path: Path,
        run_id: str,
    ) -> Path:
        return build_feature_mart_snapshot(
            raw_path=raw_path,
            output_path=output_path,
            source_mode="snapshot",
            run_id=run_id,
        )


@dataclass(frozen=True)
class ClickHouseSourceConnector:
    connector_id: str = "clickhouse_feature_slice"

    def build_feature_mart(
        self,
        *,
        raw_path: Path,
        output_path: Path,
        run_id: str,
    ) -> Path:
        return build_feature_mart_snapshot(
            raw_path=raw_path,
            output_path=output_path,
            source_mode="clickhouse",
            run_id=run_id,
        )


@dataclass(frozen=True)
class LocalJsonlExportTarget:
    target_id: str = "local_jsonl"

    def export(
        self,
        *,
        policy_result: dict[str, Any],
        output_path: Path,
        run_id: str,
    ) -> dict[str, Any]:
        export_path = export_approved(
            policy_result=policy_result, output_path=output_path
        )
        return {
            "target_id": self.target_id,
            "export_path": str(export_path),
            "export_uri": None,
            "status": "written",
        }


@dataclass(frozen=True)
class MinioJsonlExportTarget:
    target_id: str = "minio_jsonl"

    def export(
        self,
        *,
        policy_result: dict[str, Any],
        output_path: Path,
        run_id: str,
    ) -> dict[str, Any]:
        export_path = export_approved(
            policy_result=policy_result, output_path=output_path
        )
        if not minio_is_configured():
            raise ValueError(
                "Selected export target requires MinIO configuration, "
                "but MinIO environment settings are missing."
            )
        export_uri = upload_export_to_minio(export_path=export_path, run_id=run_id)
        return {
            "target_id": self.target_id,
            "export_path": str(export_path),
            "export_uri": export_uri,
            "status": "written_and_uploaded",
        }


_SOURCE_CONNECTORS: dict[str, SourceConnector] = {
    "snapshot_jsonl": SnapshotSourceConnector(),
    "clickhouse_feature_slice": ClickHouseSourceConnector(),
}

_EXPORT_TARGETS: dict[str, ExportTarget] = {
    "local_jsonl": LocalJsonlExportTarget(),
    "minio_jsonl": MinioJsonlExportTarget(),
}


def supported_source_connector_ids() -> set[str]:
    return set(_SOURCE_CONNECTORS)


def supported_export_target_ids() -> set[str]:
    return set(_EXPORT_TARGETS)


def _resolve_profile(
    profile_id: str,
) -> tuple[dict[str, Any], SourceConnector, ExportTarget]:
    profile = get_integration_profile(profile_id)
    source_id = str(profile.get("source_id", "")).strip()
    export_id = str(profile.get("export_id", "")).strip()
    if source_id not in _SOURCE_CONNECTORS:
        raise ValueError(
            "No runtime source connector implementation for profile "
            f"{profile_id}: {source_id}"
        )
    if export_id not in _EXPORT_TARGETS:
        raise ValueError(
            "No runtime export target implementation for profile "
            f"{profile_id}: {export_id}"
        )
    return profile, _SOURCE_CONNECTORS[source_id], _EXPORT_TARGETS[export_id]


def build_feature_mart_for_profile(
    *,
    profile_id: str,
    raw_path: Path,
    run_id: str,
    output_path: Path = FEATURE_MART_PATH,
) -> tuple[Path, dict[str, Any]]:
    profile, source_connector, export_target = _resolve_profile(profile_id)
    feature_mart_path = source_connector.build_feature_mart(
        raw_path=raw_path,
        output_path=output_path,
        run_id=run_id,
    )
    return feature_mart_path, {
        "profile_id": profile_id,
        "source_id": source_connector.connector_id,
        "export_id": export_target.target_id,
        "implementation_status": profile.get("implementation_status", "unknown"),
    }


def export_for_profile(
    *,
    profile_id: str,
    policy_result: dict[str, Any],
    run_id: str,
    output_path: Path = EXPORT_PATH,
) -> dict[str, Any]:
    profile, source_connector, export_target = _resolve_profile(profile_id)
    export_meta = export_target.export(
        policy_result=policy_result,
        output_path=output_path,
        run_id=run_id,
    )
    return {
        **export_meta,
        "profile_id": profile_id,
        "source_id": source_connector.connector_id,
        "export_id": export_target.target_id,
        "profile_status": profile.get("implementation_status", "unknown"),
    }
