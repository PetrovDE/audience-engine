from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import DELIVERY_DIR
from .delivery_contract import CRM_CSV_COLUMNS, StagedAudienceRow, sort_staged_rows
from .delivery_store import (
    probe_delivery_postgres_connectivity,
    validate_delivery_postgres_config,
    write_crm_postgres_outbox,
)


@dataclass(frozen=True)
class DeliveryMaterialization:
    source_row_count: int
    rows_materialized: int
    rows_written: int
    rows_skipped_conflict: int
    artifact_uri: str | None
    target_payload_by_customer: dict[str, dict[str, Any]]
    inserted_customer_ids: set[str] | None = None


class DeliveryTargetAdapter(Protocol):
    target_id: str
    runtime_readiness_mode: str

    def validate_config(self) -> None: ...
    def probe_connectivity(self) -> None: ...

    def materialize(
        self,
        *,
        rows: list[StagedAudienceRow],
        delivery_job_id: str,
    ) -> DeliveryMaterialization: ...


@dataclass(frozen=True)
class CrmCsvFileTarget:
    target_id: str = "crm_csv_file"
    runtime_readiness_mode: str = "config_only"

    def validate_config(self) -> None:
        return None

    def probe_connectivity(self) -> None:
        return None

    def _output_path(self, run_id: str, delivery_job_id: str) -> Path:
        return (
            DELIVERY_DIR
            / "crm_csv_file"
            / f"run_id={run_id}"
            / f"delivery_job_id={delivery_job_id}"
            / "crm_delivery_audience.csv"
        )

    def materialize(
        self,
        *,
        rows: list[StagedAudienceRow],
        delivery_job_id: str,
    ) -> DeliveryMaterialization:
        if not rows:
            return DeliveryMaterialization(
                source_row_count=0,
                rows_materialized=0,
                rows_written=0,
                rows_skipped_conflict=0,
                artifact_uri=None,
                target_payload_by_customer={},
                inserted_customer_ids=set(),
            )

        ordered = sort_staged_rows(rows)
        output_path = self._output_path(ordered[0].run_id, delivery_job_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        delivered_ts = datetime.now(timezone.utc)

        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(CRM_CSV_COLUMNS))
            writer.writeheader()
            for row in ordered:
                writer.writerow(
                    row.to_crm_csv_row(
                        delivery_target_id=self.target_id,
                        delivery_job_id=delivery_job_id,
                        delivery_status="materialized",
                        delivered_ts=delivered_ts,
                    )
                )

        payload_by_customer = {
            row.customer_id: {
                "csv_artifact_path": str(output_path),
                "csv_schema": "crm_csv_file_v1",
            }
            for row in ordered
        }
        row_count = len(ordered)
        return DeliveryMaterialization(
            source_row_count=row_count,
            rows_materialized=row_count,
            rows_written=row_count,
            rows_skipped_conflict=0,
            artifact_uri=str(output_path),
            target_payload_by_customer=payload_by_customer,
            inserted_customer_ids=set(payload_by_customer),
        )


@dataclass(frozen=True)
class CrmPostgresOutboxTarget:
    target_id: str = "crm_postgres_outbox"
    runtime_readiness_mode: str = "config_and_connectivity"

    def validate_config(self) -> None:
        errors = validate_delivery_postgres_config()
        if errors:
            raise ValueError("; ".join(errors))

    def probe_connectivity(self) -> None:
        probe_delivery_postgres_connectivity()

    def materialize(
        self,
        *,
        rows: list[StagedAudienceRow],
        delivery_job_id: str,
    ) -> DeliveryMaterialization:
        outbox_meta = write_crm_postgres_outbox(
            rows=rows,
            delivery_target_id=self.target_id,
            delivery_job_id=delivery_job_id,
        )
        inserted_ids = set(outbox_meta["inserted_customer_ids"])
        payload_by_customer = {
            customer_id: {
                "outbox_delivery_job_id": delivery_job_id,
                "outbox_status": "pending",
            }
            for customer_id in inserted_ids
        }
        return DeliveryMaterialization(
            source_row_count=int(outbox_meta["rows_attempted"]),
            rows_materialized=int(outbox_meta["rows_attempted"]),
            rows_written=int(outbox_meta["rows_written"]),
            rows_skipped_conflict=int(outbox_meta["rows_skipped_conflict"]),
            artifact_uri=None,
            target_payload_by_customer=payload_by_customer,
            inserted_customer_ids=inserted_ids,
        )


_DELIVERY_TARGETS: dict[str, DeliveryTargetAdapter] = {
    "crm_csv_file": CrmCsvFileTarget(),
    "crm_postgres_outbox": CrmPostgresOutboxTarget(),
}


def supported_delivery_target_ids() -> set[str]:
    return set(_DELIVERY_TARGETS)


def get_delivery_target_adapter(target_id: str) -> DeliveryTargetAdapter:
    target = _DELIVERY_TARGETS.get(target_id)
    if target is None:
        raise ValueError(f"No runtime delivery target implementation for: {target_id}")
    return target


def _runtime_readiness_status(target: DeliveryTargetAdapter) -> dict[str, Any]:
    mode = str(getattr(target, "runtime_readiness_mode", "config_only"))
    config_errors: list[str] = []
    connectivity_errors: list[str] = []
    try:
        target.validate_config()
    except Exception as exc:
        config_errors.append(str(exc))

    connectivity_checked = mode == "config_and_connectivity"
    connectivity_valid: bool | None = None
    if connectivity_checked:
        if config_errors:
            connectivity_valid = False
        else:
            try:
                target.probe_connectivity()
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


def annotate_delivery_runtime_readiness(
    *,
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in targets:
        item = dict(row)
        target_id = str(item.get("delivery_target_id", "")).strip()
        implemented = item.get("implementation_status") == "implemented"
        target = _DELIVERY_TARGETS.get(target_id)
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
                    "No runtime delivery target implementation is registered."
                ],
                "runtime_config_valid": False,
                "runtime_connectivity_checked": False,
                "runtime_connectivity_valid": None,
                "runtime_readiness_mode": "runtime_missing",
            }
        else:
            readiness = _runtime_readiness_status(target)
        item.update(readiness)
        rows.append(item)
    return rows
