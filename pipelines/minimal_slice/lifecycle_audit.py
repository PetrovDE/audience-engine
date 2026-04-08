from __future__ import annotations

import json
from typing import Any

from .config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)


def _psycopg():
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for lifecycle audit persistence"
        ) from exc
    return psycopg


def _postgres_conninfo() -> str:
    return (
        f"host={POSTGRES_HOST} "
        f"port={POSTGRES_PORT} "
        f"dbname={POSTGRES_DB} "
        f"user={POSTGRES_USER} "
        f"password={POSTGRES_PASSWORD}"
    )


def _ensure_lifecycle_audit_table() -> None:
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS index_lifecycle_audit (
                    id BIGSERIAL PRIMARY KEY,
                    action TEXT NOT NULL CHECK (
                        action IN (
                            'validate_generation',
                            'promote_alias',
                            'rollback_alias'
                        )
                    ),
                    alias_name TEXT NOT NULL,
                    target_collection_name TEXT,
                    previous_collection_name TEXT,
                    actor_role TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failed')),
                    details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    action_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION forbid_index_lifecycle_audit_mutation()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION 'index_lifecycle_audit is append-only';
                END;
                $$;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS trg_index_lifecycle_audit_no_update_delete
                ON index_lifecycle_audit;
                """
            )
            cur.execute(
                """
                CREATE TRIGGER trg_index_lifecycle_audit_no_update_delete
                BEFORE UPDATE OR DELETE ON index_lifecycle_audit
                FOR EACH ROW EXECUTE FUNCTION forbid_index_lifecycle_audit_mutation();
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_index_lifecycle_audit_alias_ts
                ON index_lifecycle_audit (alias_name, action_ts DESC);
                """
            )
        conn.commit()


def record_lifecycle_action(
    *,
    action: str,
    alias_name: str,
    target_collection_name: str | None,
    previous_collection_name: str | None,
    actor_role: str,
    actor_id: str,
    outcome: str,
    details: dict[str, Any] | None = None,
) -> None:
    _ensure_lifecycle_audit_table()
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO index_lifecycle_audit (
                    action,
                    alias_name,
                    target_collection_name,
                    previous_collection_name,
                    actor_role,
                    actor_id,
                    outcome,
                    details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    action,
                    alias_name,
                    target_collection_name,
                    previous_collection_name,
                    actor_role,
                    actor_id,
                    outcome,
                    json.dumps(details or {}),
                ),
            )
        conn.commit()


def list_lifecycle_actions(
    *,
    limit: int = 50,
    alias_name: str | None = None,
) -> list[dict[str, Any]]:
    _ensure_lifecycle_audit_table()
    safe_limit = max(1, min(limit, 200))
    clauses: list[str] = []
    params: list[Any] = []
    if alias_name:
        clauses.append("alias_name = %s")
        params.append(alias_name)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT id, action, alias_name, target_collection_name, "
        "previous_collection_name, "
        "actor_role, actor_id, outcome, details, action_ts "
        f"FROM index_lifecycle_audit {where_sql} "
        "ORDER BY action_ts DESC, id DESC LIMIT %s"
    )
    params.append(safe_limit)
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        details = row[8]
        if isinstance(details, str):
            details = json.loads(details)
        out.append(
            {
                "id": int(row[0]),
                "action": row[1],
                "alias_name": row[2],
                "target_collection_name": row[3],
                "previous_collection_name": row[4],
                "actor_role": row[5],
                "actor_id": row[6],
                "outcome": row[7],
                "details": details or {},
                "action_ts": row[9].isoformat() if row[9] else None,
            }
        )
    return out
