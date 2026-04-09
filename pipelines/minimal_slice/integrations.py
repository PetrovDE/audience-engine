from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import EXPORT_PATH, FEATURE_MART_PATH
from .control_plane import get_integration_profile
from .export_table import (
    probe_postgres_export_table_connectivity,
    validate_postgres_export_table_config,
    write_approved_to_postgres_export_table,
)
from .exporter import export_approved
from .feature_mart import build_feature_mart_snapshot
from .storage import (
    minio_is_configured,
    probe_clickhouse_source_connectivity,
    probe_minio_connectivity,
    upload_export_to_minio,
    validate_clickhouse_source_config,
)


class SourceConnector(Protocol):
    connector_id: str
    runtime_readiness_mode: str

    def validate_config(self) -> None: ...
    def probe_connectivity(self) -> None: ...

    def build_feature_mart(
        self,
        *,
        raw_path: Path,
        output_path: Path,
        run_id: str,
    ) -> Path: ...


class ExportTarget(Protocol):
    target_id: str
    runtime_readiness_mode: str

    def validate_config(self) -> None: ...
    def probe_connectivity(self) -> None: ...

    def export(
        self,
        *,
        policy_result: dict[str, Any],
        output_path: Path,
        run_id: str,
        export_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SnapshotSourceConnector:
    connector_id: str = "snapshot_jsonl"
    runtime_readiness_mode: str = "config_only"

    def validate_config(self) -> None:
        return None

    def probe_connectivity(self) -> None:
        return None

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
    runtime_readiness_mode: str = "config_and_connectivity"

    def validate_config(self) -> None:
        errors = validate_clickhouse_source_config()
        if errors:
            raise ValueError("; ".join(errors))

    def probe_connectivity(self) -> None:
        probe_clickhouse_source_connectivity()

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
    runtime_readiness_mode: str = "config_only"

    def validate_config(self) -> None:
        return None

    def probe_connectivity(self) -> None:
        return None

    def export(
        self,
        *,
        policy_result: dict[str, Any],
        output_path: Path,
        run_id: str,
        export_context: dict[str, Any] | None = None,
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
    runtime_readiness_mode: str = "config_and_connectivity"

    def validate_config(self) -> None:
        if not minio_is_configured():
            raise ValueError(
                "Selected export target requires MinIO configuration, "
                "but MinIO environment settings are missing."
            )

    def probe_connectivity(self) -> None:
        probe_minio_connectivity()

    def export(
        self,
        *,
        policy_result: dict[str, Any],
        output_path: Path,
        run_id: str,
        export_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        export_path = export_approved(
            policy_result=policy_result, output_path=output_path
        )
        export_uri = upload_export_to_minio(export_path=export_path, run_id=run_id)
        return {
            "target_id": self.target_id,
            "export_path": str(export_path),
            "export_uri": export_uri,
            "status": "written_and_uploaded",
        }


@dataclass(frozen=True)
class PostgresExportTableTarget:
    target_id: str = "postgres_export_table"
    runtime_readiness_mode: str = "config_and_connectivity"

    def validate_config(self) -> None:
        errors = validate_postgres_export_table_config()
        if errors:
            raise ValueError("; ".join(errors))

    def probe_connectivity(self) -> None:
        probe_postgres_export_table_connectivity()

    def export(
        self,
        *,
        policy_result: dict[str, Any],
        output_path: Path,
        run_id: str,
        export_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not export_context:
            raise ValueError(
                "Postgres export-table connector requires "
                "export_context with run lineage"
            )
        export_path = export_approved(
            policy_result=policy_result,
            output_path=output_path,
        )
        write_meta = write_approved_to_postgres_export_table(
            policy_result=policy_result,
            export_context=export_context,
        )
        rows_attempted = int(write_meta["rows_attempted"])
        rows_written = int(write_meta["rows_written"])
        rows_skipped_conflict = int(write_meta["rows_skipped_conflict"])
        if rows_attempted == 0:
            connector_status = "written_no_rows"
        elif rows_skipped_conflict == 0:
            connector_status = "written_and_persisted"
        elif rows_written > 0:
            connector_status = "written_and_partially_persisted"
        else:
            connector_status = "written_conflicts_only"
        return {
            "target_id": self.target_id,
            "export_path": str(export_path),
            "export_uri": None,
            "status": connector_status,
            "postgres_table": write_meta["table"],
            "rows_attempted": rows_attempted,
            "rows_written": rows_written,
            "rows_skipped_conflict": rows_skipped_conflict,
        }


_SOURCE_CONNECTORS: dict[str, SourceConnector] = {
    "snapshot_jsonl": SnapshotSourceConnector(),
    "clickhouse_feature_slice": ClickHouseSourceConnector(),
}

_EXPORT_TARGETS: dict[str, ExportTarget] = {
    "local_jsonl": LocalJsonlExportTarget(),
    "minio_jsonl": MinioJsonlExportTarget(),
    "postgres_export_table": PostgresExportTableTarget(),
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
    source_connector.validate_config()
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
    export_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile, source_connector, export_target = _resolve_profile(profile_id)
    export_target.validate_config()
    export_meta = export_target.export(
        policy_result=policy_result,
        output_path=output_path,
        run_id=run_id,
        export_context=export_context,
    )
    return {
        **export_meta,
        "profile_id": profile_id,
        "source_id": source_connector.connector_id,
        "export_id": export_target.target_id,
        "profile_status": profile.get("implementation_status", "unknown"),
    }


def _runtime_readiness_status(connector: Any) -> dict[str, Any]:
    mode = str(getattr(connector, "runtime_readiness_mode", "config_only"))
    config_errors: list[str] = []
    connectivity_errors: list[str] = []
    try:
        connector.validate_config()
    except Exception as exc:
        config_errors.append(str(exc))

    connectivity_checked = mode == "config_and_connectivity"
    connectivity_valid: bool | None = None
    if connectivity_checked:
        if config_errors:
            connectivity_valid = False
        else:
            try:
                connector.probe_connectivity()
                connectivity_valid = True
            except Exception as exc:
                connectivity_valid = False
                connectivity_errors.append(str(exc))

    errors = [
        *config_errors,
        *[f"connectivity: {msg}" for msg in connectivity_errors],
    ]
    runnable = not config_errors and (connectivity_valid is not False)
    return {
        "runtime_runnable": runnable,
        "runtime_validation_errors": errors,
        "runtime_config_valid": not config_errors,
        "runtime_connectivity_checked": connectivity_checked,
        "runtime_connectivity_valid": connectivity_valid,
        "runtime_readiness_mode": mode,
    }


def annotate_runtime_readiness(
    *,
    sources: list[dict[str, Any]],
    exports: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    source_rows: list[dict[str, Any]] = []
    export_rows: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []

    source_status_by_id: dict[str, dict[str, Any]] = {}
    for row in sources:
        item = dict(row)
        source_id = str(item.get("source_id", "")).strip()
        implemented = item.get("implementation_status") == "implemented"
        connector = _SOURCE_CONNECTORS.get(source_id)
        if not implemented:
            readiness = {
                "runtime_runnable": False,
                "runtime_validation_errors": [],
                "runtime_config_valid": False,
                "runtime_connectivity_checked": False,
                "runtime_connectivity_valid": None,
                "runtime_readiness_mode": "not_implemented",
            }
        elif connector is None:
            readiness = {
                "runtime_runnable": False,
                "runtime_validation_errors": [
                    "No runtime source connector implementation is registered."
                ],
                "runtime_config_valid": False,
                "runtime_connectivity_checked": False,
                "runtime_connectivity_valid": None,
                "runtime_readiness_mode": "runtime_missing",
            }
        else:
            readiness = _runtime_readiness_status(connector)
        item.update(readiness)
        source_status_by_id[source_id] = readiness
        source_rows.append(item)

    export_status_by_id: dict[str, dict[str, Any]] = {}
    for row in exports:
        item = dict(row)
        export_id = str(item.get("export_id", "")).strip()
        implemented = item.get("implementation_status") == "implemented"
        target = _EXPORT_TARGETS.get(export_id)
        if not implemented:
            readiness = {
                "runtime_runnable": False,
                "runtime_validation_errors": [],
                "runtime_config_valid": False,
                "runtime_connectivity_checked": False,
                "runtime_connectivity_valid": None,
                "runtime_readiness_mode": "not_implemented",
            }
        elif target is None:
            readiness = {
                "runtime_runnable": False,
                "runtime_validation_errors": [
                    "No runtime export target implementation is registered."
                ],
                "runtime_config_valid": False,
                "runtime_connectivity_checked": False,
                "runtime_connectivity_valid": None,
                "runtime_readiness_mode": "runtime_missing",
            }
        else:
            readiness = _runtime_readiness_status(target)
        item.update(readiness)
        export_status_by_id[export_id] = readiness
        export_rows.append(item)

    for row in profiles:
        item = dict(row)
        profile_status = item.get("implementation_status")
        source_id = str(item.get("source_id", "")).strip()
        export_id = str(item.get("export_id", "")).strip()
        errors: list[str] = []
        source_status = source_status_by_id.get(
            source_id,
            {
                "runtime_runnable": False,
                "runtime_validation_errors": [
                    "Source connector is unknown in runtime registry."
                ],
            },
        )
        export_status = export_status_by_id.get(
            export_id,
            {
                "runtime_runnable": False,
                "runtime_validation_errors": [
                    "Export target is unknown in runtime registry."
                ],
            },
        )
        source_runnable = bool(source_status.get("runtime_runnable"))
        source_errors = list(source_status.get("runtime_validation_errors") or [])
        export_runnable = bool(export_status.get("runtime_runnable"))
        export_errors = list(export_status.get("runtime_validation_errors") or [])
        if profile_status != "implemented":
            errors.append("Profile is not marked as implemented.")
        if not source_runnable:
            errors.append(f"Source connector {source_id!r} is not runnable.")
            errors.extend([f"source: {msg}" for msg in source_errors])
        if not export_runnable:
            errors.append(f"Export target {export_id!r} is not runnable.")
            errors.extend([f"export: {msg}" for msg in export_errors])
        item["runtime_runnable"] = profile_status == "implemented" and not errors
        item["runtime_validation_errors"] = errors
        item["runtime_readiness_mode"] = (
            "profile_config_and_connectivity"
            if profile_status == "implemented"
            else "not_implemented"
        )
        profile_rows.append(item)

    return {"sources": source_rows, "exports": export_rows, "profiles": profile_rows}
