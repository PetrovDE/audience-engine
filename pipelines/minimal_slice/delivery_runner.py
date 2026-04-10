from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import control_plane, delivery_registry, delivery_store, delivery_targets
from .delivery_contract import sort_staged_rows


def list_delivery_targets(*, include_planned: bool = True) -> list[dict[str, Any]]:
    targets = delivery_registry.list_delivery_targets(include_planned=include_planned)
    return delivery_targets.annotate_delivery_runtime_readiness(targets=targets)


def execute_delivery_for_run(
    *,
    run_id: str,
    delivery_target_id: str,
    trigger_source: str,
    requested_by_role: str,
    requested_by_id: str,
) -> dict[str, Any]:
    delivery_registry.ensure_selectable_delivery_target(
        delivery_target_id,
        selection_kind="Selected",
    )
    adapter = delivery_targets.get_delivery_target_adapter(delivery_target_id)
    adapter.validate_config()

    campaign_id = delivery_store.resolve_run_campaign_id(run_id)
    run_export_id = delivery_store.resolve_run_export_target_id(run_id)
    if run_export_id:
        export_target = next(
            (
                row
                for row in control_plane.list_export_targets(include_planned=True)
                if row.get("export_id") == run_export_id
            ),
            None,
        )
        if export_target is None:
            raise ValueError(f"Unknown export target in run lineage: {run_export_id}")
        delivery_registry.ensure_delivery_target_compatible_with_export(
            delivery_target_id,
            export_target=export_target,
            selection_kind="Selected",
        )

    staged_rows = sort_staged_rows(delivery_store.fetch_staged_audience_rows(run_id))
    if delivery_target_id == "crm_postgres_outbox":
        return delivery_store.execute_crm_postgres_outbox_delivery_atomic(
            run_id=run_id,
            campaign_id=campaign_id,
            delivery_target_id=delivery_target_id,
            trigger_source=trigger_source,
            requested_by_role=requested_by_role,
            requested_by_id=requested_by_id,
            staged_rows=staged_rows,
        )

    now = datetime.now(timezone.utc)
    job = delivery_store.create_delivery_job(
        run_id=run_id,
        campaign_id=campaign_id,
        delivery_target_id=delivery_target_id,
        trigger_source=trigger_source,
        requested_by_role=requested_by_role,
        requested_by_id=requested_by_id,
    )
    delivery_job_id = str(job["delivery_job_id"])

    delivery_store.append_delivery_attempt(
        delivery_job_id=delivery_job_id,
        run_id=run_id,
        campaign_id=campaign_id,
        delivery_target_id=delivery_target_id,
        attempt_status="pending",
        details={"source_row_count": len(staged_rows)},
        attempt_ts=now,
    )
    if not staged_rows:
        completed_at = datetime.now(timezone.utc)
        final_status = "skipped_no_source_rows"
        delivery_store.complete_delivery_job(
            delivery_job_id=delivery_job_id,
            status=final_status,
            rows_delivered=0,
            rows_skipped_conflict=0,
            error_detail="No staged rows found in audience_export_staging for run",
            completed_at=completed_at,
        )
        delivery_store.append_delivery_attempt(
            delivery_job_id=delivery_job_id,
            run_id=run_id,
            campaign_id=campaign_id,
            delivery_target_id=delivery_target_id,
            attempt_status=final_status,
            details={"reason": "no_source_rows_in_staging"},
            attempt_ts=completed_at,
        )
        return {
            "delivery_job_id": delivery_job_id,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "delivery_target_id": delivery_target_id,
            "status": final_status,
            "source_row_count": 0,
            "rows_materialized": 0,
            "rows_delivered": 0,
            "rows_skipped_conflict": 0,
            "artifact_uri": None,
            "completed_at": completed_at.isoformat(),
        }

    try:
        materialized_at = datetime.now(timezone.utc)
        materialization = adapter.materialize(
            rows=staged_rows,
            delivery_job_id=delivery_job_id,
        )

        delivery_store.mark_delivery_job_materialized(
            delivery_job_id=delivery_job_id,
            source_row_count=materialization.source_row_count,
            rows_materialized=materialization.rows_materialized,
            artifact_uri=materialization.artifact_uri,
            materialized_at=materialized_at,
        )
        delivery_store.append_delivery_attempt(
            delivery_job_id=delivery_job_id,
            run_id=run_id,
            campaign_id=campaign_id,
            delivery_target_id=delivery_target_id,
            attempt_status="materialized",
            details={
                "rows_materialized": materialization.rows_materialized,
                "rows_written": materialization.rows_written,
                "rows_skipped_conflict": materialization.rows_skipped_conflict,
                "artifact_uri": materialization.artifact_uri,
            },
            attempt_ts=materialized_at,
        )

        delivered_at = datetime.now(timezone.utc)
        record_meta = delivery_store.insert_delivery_records(
            rows=staged_rows,
            delivery_target_id=delivery_target_id,
            delivery_job_id=delivery_job_id,
            delivery_status="delivered",
            delivery_artifact_uri=materialization.artifact_uri,
            materialized_ts=materialized_at,
            delivered_ts=delivered_at,
            target_payload_by_customer=materialization.target_payload_by_customer,
        )
        rows_delivered = int(record_meta["rows_written"])
        rows_skipped_conflict = int(record_meta["rows_skipped_conflict"])

        if staged_rows and rows_delivered == 0 and rows_skipped_conflict > 0:
            final_status = "skipped_conflict"
        else:
            final_status = "delivered"

        delivery_store.complete_delivery_job(
            delivery_job_id=delivery_job_id,
            status=final_status,
            rows_delivered=rows_delivered,
            rows_skipped_conflict=rows_skipped_conflict,
            error_detail=None,
            completed_at=delivered_at,
        )
        delivery_store.append_delivery_attempt(
            delivery_job_id=delivery_job_id,
            run_id=run_id,
            campaign_id=campaign_id,
            delivery_target_id=delivery_target_id,
            attempt_status=final_status,
            details={
                "rows_delivered": rows_delivered,
                "rows_skipped_conflict": rows_skipped_conflict,
                "artifact_uri": materialization.artifact_uri,
            },
            attempt_ts=delivered_at,
        )

        return {
            "delivery_job_id": delivery_job_id,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "delivery_target_id": delivery_target_id,
            "status": final_status,
            "source_row_count": len(staged_rows),
            "rows_materialized": int(materialization.rows_materialized),
            "rows_delivered": rows_delivered,
            "rows_skipped_conflict": rows_skipped_conflict,
            "artifact_uri": materialization.artifact_uri,
            "completed_at": delivered_at.isoformat(),
        }
    except Exception as exc:
        failed_at = datetime.now(timezone.utc)
        delivery_store.complete_delivery_job(
            delivery_job_id=delivery_job_id,
            status="failed",
            rows_delivered=0,
            rows_skipped_conflict=0,
            error_detail=str(exc),
            completed_at=failed_at,
        )
        delivery_store.append_delivery_attempt(
            delivery_job_id=delivery_job_id,
            run_id=run_id,
            campaign_id=campaign_id,
            delivery_target_id=delivery_target_id,
            attempt_status="failed",
            details={"error": str(exc)},
            attempt_ts=failed_at,
        )
        raise


def list_recent_delivery_jobs(*, limit: int = 20) -> list[dict[str, Any]]:
    return delivery_store.list_recent_delivery_jobs(limit=limit)


def list_recent_delivery_attempts(
    *,
    limit: int = 50,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    return delivery_store.list_recent_delivery_attempts(limit=limit, run_id=run_id)


def latest_delivery_summary_for_run(run_id: str) -> dict[str, Any] | None:
    return delivery_store.latest_delivery_summary_for_run(run_id)


def list_delivery_records_for_run(
    *,
    run_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return delivery_store.list_delivery_records_for_run(run_id=run_id, limit=limit)
