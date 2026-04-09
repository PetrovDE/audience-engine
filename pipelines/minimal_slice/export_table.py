from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .config import (
    EXPORT_POSTGRES_DB,
    EXPORT_POSTGRES_HOST,
    EXPORT_POSTGRES_PASSWORD,
    EXPORT_POSTGRES_PORT,
    EXPORT_POSTGRES_SCHEMA,
    EXPORT_POSTGRES_SSLMODE,
    EXPORT_POSTGRES_TABLE,
    EXPORT_POSTGRES_USER,
)

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _psycopg():
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for Postgres export-table connector"
        ) from exc
    return psycopg


def _validate_identifier(name: str, *, field: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError(f"{field} is required for Postgres export-table connector")
    if not _IDENTIFIER_PATTERN.match(value):
        raise ValueError(
            f"{field} must match [A-Za-z_][A-Za-z0-9_]* "
            f"for Postgres export-table connector: {value!r}"
        )
    return value


def _validate_required(value: str, *, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{field} is required for Postgres export-table connector")
    return resolved


def _ensure_uuid(value: str, *, field: str) -> str:
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError(
            f"{field} must be a UUID for Postgres export-table connector: {value!r}"
        ) from exc
    return value


def _postgres_conninfo() -> str:
    host = _validate_required(EXPORT_POSTGRES_HOST, field="EXPORT_POSTGRES_HOST")
    db = _validate_required(EXPORT_POSTGRES_DB, field="EXPORT_POSTGRES_DB")
    user = _validate_required(EXPORT_POSTGRES_USER, field="EXPORT_POSTGRES_USER")
    password = _validate_required(
        EXPORT_POSTGRES_PASSWORD,
        field="EXPORT_POSTGRES_PASSWORD",
    )
    parts = [
        f"host={host}",
        f"port={int(EXPORT_POSTGRES_PORT)}",
        f"dbname={db}",
        f"user={user}",
        f"password={password}",
    ]
    sslmode = EXPORT_POSTGRES_SSLMODE.strip()
    if sslmode:
        parts.append(f"sslmode={sslmode}")
    return " ".join(parts)


def validate_postgres_export_table_config() -> list[str]:
    errors: list[str] = []
    try:
        _validate_required(EXPORT_POSTGRES_HOST, field="EXPORT_POSTGRES_HOST")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        _validate_required(EXPORT_POSTGRES_DB, field="EXPORT_POSTGRES_DB")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        _validate_required(EXPORT_POSTGRES_USER, field="EXPORT_POSTGRES_USER")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        _validate_required(EXPORT_POSTGRES_PASSWORD, field="EXPORT_POSTGRES_PASSWORD")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        _validate_identifier(EXPORT_POSTGRES_SCHEMA, field="EXPORT_POSTGRES_SCHEMA")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        _validate_identifier(EXPORT_POSTGRES_TABLE, field="EXPORT_POSTGRES_TABLE")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        if int(EXPORT_POSTGRES_PORT) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(
            "EXPORT_POSTGRES_PORT must be a positive integer "
            "for Postgres export-table connector"
        )
    return errors


def _require_export_context(export_context: dict[str, Any]) -> dict[str, Any]:
    required_fields = [
        "run_id",
        "campaign_id",
        "policy_version",
        "fs_version",
        "emb_version",
        "model_version",
        "index_alias",
        "index_generation",
        "integration_profile_id",
        "source_id",
        "export_id",
    ]
    missing = [
        field
        for field in required_fields
        if str(export_context.get(field, "")).strip() == ""
    ]
    if missing:
        raise ValueError(
            "Postgres export-table connector requires export_context fields: "
            + ", ".join(sorted(missing))
        )
    return export_context


def _approved_rows(policy_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in policy_result.get("results", []):
        if str(row.get("decision", "")).strip().lower() != "approve":
            continue
        customer_id = str(row.get("customer_id", "")).strip()
        if not customer_id:
            continue
        rows.append(
            {
                "customer_id": customer_id,
                "score": float(row.get("score", 0.0)),
                "decision": "approve",
                "reasons": row.get("reasons", []),
            }
        )
    return rows


def write_approved_to_postgres_export_table(
    *,
    policy_result: dict[str, Any],
    export_context: dict[str, Any],
) -> dict[str, Any]:
    context = _require_export_context(dict(export_context))
    config_errors = validate_postgres_export_table_config()
    if config_errors:
        raise ValueError("; ".join(config_errors))

    run_id = _ensure_uuid(str(context["run_id"]), field="export_context.run_id")
    campaign_id = str(context["campaign_id"])
    channel = str(context.get("channel", "email"))
    exported_ts = str(
        context.get("exported_ts") or datetime.now(timezone.utc).isoformat()
    )
    schema_name = _validate_identifier(
        EXPORT_POSTGRES_SCHEMA, field="EXPORT_POSTGRES_SCHEMA"
    )
    table_name = _validate_identifier(
        EXPORT_POSTGRES_TABLE, field="EXPORT_POSTGRES_TABLE"
    )

    approved = _approved_rows(policy_result)
    if not approved:
        return {
            "rows_written": 0,
            "table": f"{schema_name}.{table_name}",
            "status": "no_rows",
        }

    insert_rows: list[tuple[Any, ...]] = []
    for rank, row in enumerate(approved, start=1):
        insert_rows.append(
            (
                run_id,
                campaign_id,
                row["customer_id"],
                row["decision"],
                row["score"],
                rank,
                channel,
                str(context["policy_version"]),
                str(context["fs_version"]),
                str(context["emb_version"]),
                str(context["model_version"]),
                str(context["index_alias"]),
                str(context["index_generation"]),
                str(context["integration_profile_id"]),
                str(context["source_id"]),
                str(context["export_id"]),
                exported_ts,
                json.dumps(
                    {
                        "reason_codes": [
                            reason.get("reason_code")
                            for reason in row.get("reasons", [])
                            if isinstance(reason, dict) and reason.get("reason_code")
                        ],
                    }
                ),
            )
        )

    insert_sql = f"""
        INSERT INTO {schema_name}.{table_name} (
            run_id,
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
        )
        VALUES (
            %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s::timestamptz, %s::jsonb
        )
        ON CONFLICT (run_id, customer_id) DO NOTHING
    """

    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.executemany(insert_sql, insert_rows)
        conn.commit()

    return {
        "rows_written": len(insert_rows),
        "table": f"{schema_name}.{table_name}",
        "status": "written",
    }
