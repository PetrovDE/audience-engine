from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from .config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_SSLMODE,
    POSTGRES_USER,
)
from .delivery_contract import StagedAudienceRow, ensure_delivery_status


def _psycopg():
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for delivery storage operations"
        ) from exc
    return psycopg, dict_row


def _validate_required(value: str, *, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{field} is required for delivery storage")
    return resolved


def _postgres_conninfo() -> str:
    host = _validate_required(POSTGRES_HOST, field="POSTGRES_HOST")
    db = _validate_required(POSTGRES_DB, field="POSTGRES_DB")
    user = _validate_required(POSTGRES_USER, field="POSTGRES_USER")
    password = _validate_required(POSTGRES_PASSWORD, field="POSTGRES_PASSWORD")
    parts = [
        f"host={host}",
        f"port={int(POSTGRES_PORT)}",
        f"dbname={db}",
        f"user={user}",
        f"password={password}",
        "connect_timeout=2",
    ]
    sslmode = POSTGRES_SSLMODE.strip()
    if sslmode:
        parts.append(f"sslmode={sslmode}")
    return " ".join(parts)


def validate_delivery_postgres_config() -> list[str]:
    errors: list[str] = []
    for field, value in (
        ("POSTGRES_HOST", POSTGRES_HOST),
        ("POSTGRES_DB", POSTGRES_DB),
        ("POSTGRES_USER", POSTGRES_USER),
        ("POSTGRES_PASSWORD", POSTGRES_PASSWORD),
    ):
        try:
            _validate_required(value, field=field)
        except ValueError as exc:
            errors.append(str(exc))
    try:
        if int(POSTGRES_PORT) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("POSTGRES_PORT must be a positive integer for delivery storage")
    return errors


def probe_delivery_postgres_connectivity() -> None:
    errors = validate_delivery_postgres_config()
    if errors:
        raise ValueError("; ".join(errors))
    psycopg, _ = _psycopg()
    try:
        with psycopg.connect(_postgres_conninfo()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as exc:
        raise RuntimeError(
            "Delivery Postgres connectivity probe failed against "
            f"host={POSTGRES_HOST!r}, db={POSTGRES_DB!r}: {exc}"
        ) from exc


def _ensure_uuid(value: str, *, field: str) -> str:
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID: {value!r}") from exc
    return value


def resolve_run_campaign_id(run_id: str) -> str:
    run_uuid = _ensure_uuid(run_id, field="run_id")
    psycopg, _ = _psycopg()
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT campaign_id FROM audience_run WHERE run_id = %s::uuid",
                (run_uuid,),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError(f"No audience_run row found for run_id={run_id}")
    campaign_id = str(row[0] or "").strip()
    if not campaign_id:
        raise ValueError(f"audience_run campaign_id is missing for run_id={run_id}")
    return campaign_id


def fetch_staged_audience_rows(run_id: str) -> list[StagedAudienceRow]:
    run_uuid = _ensure_uuid(run_id, field="run_id")
    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    run_id::text,
                    campaign_id,
                    customer_id,
                    status,
                    final_score,
                    rank,
                    channel,
                    policy_version,
                    fs_version,
                    emb_version,
                    model_version,
                    index_alias,
                    index_generation,
                    integration_profile_id,
                    source_id,
                    export_target_id,
                    exported_ts,
                    export_context
                FROM audience_export_staging
                WHERE run_id = %s::uuid
                ORDER BY rank ASC, customer_id ASC
                """,
                (run_uuid,),
            )
            rows = cur.fetchall()
    return [StagedAudienceRow.from_db_row(dict(row)) for row in rows]


def create_delivery_job(
    *,
    run_id: str,
    campaign_id: str,
    delivery_target_id: str,
    trigger_source: str,
    requested_by_role: str,
    requested_by_id: str,
) -> dict[str, Any]:
    run_uuid = _ensure_uuid(run_id, field="run_id")
    job_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    status = ensure_delivery_status("pending")

    psycopg, _ = _psycopg()
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audience_delivery_job (
                    delivery_job_id,
                    run_id,
                    campaign_id,
                    delivery_target_id,
                    trigger_source,
                    requested_by_role,
                    requested_by_id,
                    status,
                    source_row_count,
                    rows_materialized,
                    rows_delivered,
                    rows_skipped_conflict,
                    started_at
                ) VALUES (
                    %s::uuid,
                    %s::uuid,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    0,
                    0,
                    0,
                    0,
                    %s::timestamptz
                )
                """,
                (
                    job_id,
                    run_uuid,
                    campaign_id,
                    delivery_target_id,
                    trigger_source,
                    requested_by_role,
                    requested_by_id,
                    status,
                    started_at.isoformat(),
                ),
            )
        conn.commit()
    return {
        "delivery_job_id": job_id,
        "run_id": run_uuid,
        "campaign_id": campaign_id,
        "delivery_target_id": delivery_target_id,
        "status": status,
        "started_at": started_at,
    }


def mark_delivery_job_materialized(
    *,
    delivery_job_id: str,
    source_row_count: int,
    rows_materialized: int,
    artifact_uri: str | None,
    materialized_at: datetime,
) -> None:
    _ensure_uuid(delivery_job_id, field="delivery_job_id")
    status = ensure_delivery_status("materialized")
    psycopg, _ = _psycopg()
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audience_delivery_job
                SET
                    status = %s,
                    source_row_count = %s,
                    rows_materialized = %s,
                    artifact_uri = %s,
                    materialized_at = %s::timestamptz
                WHERE delivery_job_id = %s::uuid
                """,
                (
                    status,
                    max(source_row_count, 0),
                    max(rows_materialized, 0),
                    artifact_uri,
                    materialized_at.isoformat(),
                    delivery_job_id,
                ),
            )
        conn.commit()


def complete_delivery_job(
    *,
    delivery_job_id: str,
    status: str,
    rows_delivered: int,
    rows_skipped_conflict: int,
    error_detail: str | None,
    completed_at: datetime,
) -> None:
    _ensure_uuid(delivery_job_id, field="delivery_job_id")
    resolved_status = ensure_delivery_status(status)
    psycopg, _ = _psycopg()
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audience_delivery_job
                SET
                    status = %s,
                    rows_delivered = %s,
                    rows_skipped_conflict = %s,
                    error_detail = %s,
                    completed_at = %s::timestamptz
                WHERE delivery_job_id = %s::uuid
                """,
                (
                    resolved_status,
                    max(rows_delivered, 0),
                    max(rows_skipped_conflict, 0),
                    error_detail,
                    completed_at.isoformat(),
                    delivery_job_id,
                ),
            )
        conn.commit()


def append_delivery_attempt(
    *,
    delivery_job_id: str,
    run_id: str,
    campaign_id: str,
    delivery_target_id: str,
    attempt_status: str,
    details: dict[str, Any],
    attempt_ts: datetime,
) -> None:
    _ensure_uuid(delivery_job_id, field="delivery_job_id")
    run_uuid = _ensure_uuid(run_id, field="run_id")
    status = ensure_delivery_status(attempt_status)
    psycopg, _ = _psycopg()
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audience_delivery_attempt (
                    delivery_job_id,
                    run_id,
                    campaign_id,
                    delivery_target_id,
                    attempt_status,
                    details,
                    attempt_ts
                ) VALUES (
                    %s::uuid,
                    %s::uuid,
                    %s,
                    %s,
                    %s,
                    %s::jsonb,
                    %s::timestamptz
                )
                """,
                (
                    delivery_job_id,
                    run_uuid,
                    campaign_id,
                    delivery_target_id,
                    status,
                    json.dumps(details or {}),
                    attempt_ts.isoformat(),
                ),
            )
        conn.commit()


def _reason_codes(row: StagedAudienceRow) -> list[str]:
    reason_codes = row.export_context.get("reason_codes", [])
    if not isinstance(reason_codes, list):
        return []
    return [str(code) for code in reason_codes if str(code).strip()]


def _record_payload(
    row: StagedAudienceRow,
    *,
    target_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "reason_codes": _reason_codes(row),
        "final_score": row.final_score,
        "rank": row.rank,
        "channel": row.channel,
        "staging_export_context": row.export_context,
    }
    if target_payload:
        payload["target_payload"] = target_payload
    return payload


def insert_delivery_records(
    *,
    rows: Iterable[StagedAudienceRow],
    delivery_target_id: str,
    delivery_job_id: str,
    delivery_status: str,
    delivery_artifact_uri: str | None,
    materialized_ts: datetime | None,
    delivered_ts: datetime | None,
    target_payload_by_customer: dict[str, dict[str, Any]] | None = None,
    customer_id_filter: set[str] | None = None,
) -> dict[str, int]:
    _ensure_uuid(delivery_job_id, field="delivery_job_id")
    status = ensure_delivery_status(delivery_status)
    selected_rows = [
        row
        for row in rows
        if customer_id_filter is None or row.customer_id in customer_id_filter
    ]
    if not selected_rows:
        return {"rows_attempted": 0, "rows_written": 0, "rows_skipped_conflict": 0}

    insert_sql = """
        INSERT INTO audience_delivery_record (
            run_id,
            campaign_id,
            customer_id,
            delivery_target_id,
            policy_version,
            integration_profile_id,
            source_id,
            export_target_id,
            delivery_status,
            delivery_job_id,
            delivery_artifact_uri,
            delivery_payload,
            staging_exported_ts,
            materialized_ts,
            delivered_ts
        ) VALUES (
            %s::uuid,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s::uuid,
            %s,
            %s::jsonb,
            %s::timestamptz,
            %s::timestamptz,
            %s::timestamptz
        )
        ON CONFLICT (run_id, customer_id, delivery_target_id) DO NOTHING
    """

    rows_written = 0
    psycopg, _ = _psycopg()
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            for row in selected_rows:
                payload = _record_payload(
                    row,
                    target_payload=(target_payload_by_customer or {}).get(
                        row.customer_id
                    ),
                )
                cur.execute(
                    insert_sql,
                    (
                        row.run_id,
                        row.campaign_id,
                        row.customer_id,
                        delivery_target_id,
                        row.policy_version,
                        row.integration_profile_id,
                        row.source_id,
                        row.export_target_id,
                        status,
                        delivery_job_id,
                        delivery_artifact_uri,
                        json.dumps(payload),
                        row.exported_ts.isoformat(),
                        materialized_ts.isoformat() if materialized_ts else None,
                        delivered_ts.isoformat() if delivered_ts else None,
                    ),
                )
                rows_written += max(int(cur.rowcount or 0), 0)
        conn.commit()

    rows_attempted = len(selected_rows)
    return {
        "rows_attempted": rows_attempted,
        "rows_written": rows_written,
        "rows_skipped_conflict": max(rows_attempted - rows_written, 0),
    }


def write_crm_postgres_outbox(
    *,
    rows: Iterable[StagedAudienceRow],
    delivery_target_id: str,
    delivery_job_id: str,
) -> dict[str, Any]:
    _ensure_uuid(delivery_job_id, field="delivery_job_id")
    selected_rows = list(rows)
    if not selected_rows:
        return {
            "rows_attempted": 0,
            "rows_written": 0,
            "rows_skipped_conflict": 0,
            "inserted_customer_ids": set(),
        }

    insert_sql = """
        INSERT INTO audience_crm_postgres_outbox (
            run_id,
            campaign_id,
            customer_id,
            delivery_target_id,
            delivery_job_id,
            outbox_status,
            policy_version,
            integration_profile_id,
            source_id,
            export_target_id,
            staging_exported_ts,
            payload
        ) VALUES (
            %s::uuid,
            %s,
            %s,
            %s,
            %s::uuid,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s::timestamptz,
            %s::jsonb
        )
        ON CONFLICT (run_id, customer_id, delivery_target_id) DO NOTHING
    """

    inserted_customer_ids: set[str] = set()
    rows_written = 0
    psycopg, _ = _psycopg()
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            for row in selected_rows:
                payload = {
                    "final_score": row.final_score,
                    "rank": row.rank,
                    "channel": row.channel,
                    "fs_version": row.fs_version,
                    "emb_version": row.emb_version,
                    "model_version": row.model_version,
                    "index_alias": row.index_alias,
                    "index_generation": row.index_generation,
                    "reason_codes": _reason_codes(row),
                    "staging_export_context": row.export_context,
                }
                cur.execute(
                    insert_sql,
                    (
                        row.run_id,
                        row.campaign_id,
                        row.customer_id,
                        delivery_target_id,
                        delivery_job_id,
                        "pending",
                        row.policy_version,
                        row.integration_profile_id,
                        row.source_id,
                        row.export_target_id,
                        row.exported_ts.isoformat(),
                        json.dumps(payload),
                    ),
                )
                rowcount = max(int(cur.rowcount or 0), 0)
                rows_written += rowcount
                if rowcount > 0:
                    inserted_customer_ids.add(row.customer_id)
        conn.commit()

    rows_attempted = len(selected_rows)
    return {
        "rows_attempted": rows_attempted,
        "rows_written": rows_written,
        "rows_skipped_conflict": max(rows_attempted - rows_written, 0),
        "inserted_customer_ids": inserted_customer_ids,
    }


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    return serialized


def list_recent_delivery_jobs(*, limit: int = 20) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    delivery_job_id::text,
                    run_id::text,
                    campaign_id,
                    delivery_target_id,
                    trigger_source,
                    requested_by_role,
                    requested_by_id,
                    status,
                    source_row_count,
                    rows_materialized,
                    rows_delivered,
                    rows_skipped_conflict,
                    artifact_uri,
                    error_detail,
                    started_at,
                    materialized_at,
                    completed_at,
                    created_at
                FROM audience_delivery_job
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [_serialize_row(dict(row)) for row in rows]


def list_recent_delivery_attempts(
    *,
    limit: int = 50,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")

    params: list[Any] = []
    where = ""
    if run_id:
        run_uuid = _ensure_uuid(run_id, field="run_id")
        where = "WHERE run_id = %s::uuid"
        params.append(run_uuid)
    params.append(limit)

    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    id,
                    delivery_job_id::text,
                    run_id::text,
                    campaign_id,
                    delivery_target_id,
                    attempt_status,
                    details,
                    attempt_ts,
                    created_at
                FROM audience_delivery_attempt
                {where}
                ORDER BY attempt_ts DESC, id DESC
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
    return [_serialize_row(dict(row)) for row in rows]


def latest_delivery_summary_for_run(run_id: str) -> dict[str, Any] | None:
    run_uuid = _ensure_uuid(run_id, field="run_id")
    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    delivery_job_id::text,
                    run_id::text,
                    campaign_id,
                    delivery_target_id,
                    trigger_source,
                    requested_by_role,
                    requested_by_id,
                    status,
                    source_row_count,
                    rows_materialized,
                    rows_delivered,
                    rows_skipped_conflict,
                    artifact_uri,
                    error_detail,
                    started_at,
                    materialized_at,
                    completed_at,
                    created_at
                FROM audience_delivery_job
                WHERE run_id = %s::uuid
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (run_uuid,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return _serialize_row(dict(row))


def list_delivery_records_for_run(
    *,
    run_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    run_uuid = _ensure_uuid(run_id, field="run_id")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    run_id::text,
                    campaign_id,
                    customer_id,
                    delivery_target_id,
                    policy_version,
                    integration_profile_id,
                    source_id,
                    export_target_id,
                    delivery_status,
                    delivery_job_id::text,
                    delivery_artifact_uri,
                    delivery_payload,
                    staging_exported_ts,
                    materialized_ts,
                    delivered_ts,
                    created_at
                FROM audience_delivery_record
                WHERE run_id = %s::uuid
                ORDER BY id DESC
                LIMIT %s
                """,
                (run_uuid, limit),
            )
            rows = cur.fetchall()
    return [_serialize_row(dict(row)) for row in rows]
