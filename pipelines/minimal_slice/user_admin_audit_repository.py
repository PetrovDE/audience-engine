from __future__ import annotations

import json
from typing import Any

from .control_plane_registry_db import load_psycopg, postgres_conninfo
from .user_admin_schema import ensure_user_admin_schema


def _iso_timestamp(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _decode_json_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


class PostgresUserAdminAuditRepository:
    def _connect(self):
        ensure_user_admin_schema()
        psycopg, dict_row = load_psycopg()
        return psycopg.connect(postgres_conninfo(), row_factory=dict_row)

    def _serialize_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "audit_id": int(row["audit_id"]),
            "audit_action": str(row["audit_action"]),
            "actor_id": str(row["actor_id"]),
            "target_user_id": str(row["target_user_id"])
            if row.get("target_user_id")
            else None,
            "details": _decode_json_field(row.get("details")),
            "action_ts": _iso_timestamp(row.get("action_ts")),
            "created_at": _iso_timestamp(row.get("created_at")),
        }

    def append_audit_entry(
        self,
        *,
        audit_action: str,
        actor_id: str,
        target_user_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = details if isinstance(details, dict) else {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ae_user_admin_audit (
                        audit_action,
                        actor_id,
                        target_user_id,
                        details
                    )
                    VALUES (%s, %s, %s::uuid, %s::jsonb)
                    RETURNING
                        audit_id,
                        audit_action,
                        actor_id,
                        target_user_id::text AS target_user_id,
                        details,
                        action_ts,
                        created_at
                    """,
                    (
                        audit_action,
                        actor_id,
                        target_user_id,
                        json.dumps(payload, default=str),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Failed to append user admin audit row.")
        return self._serialize_audit(row)

    def list_audit_entries(
        self,
        *,
        target_user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        where_sql = ""
        params: tuple[Any, ...]
        if target_user_id:
            where_sql = "WHERE target_user_id = %s::uuid"
            params = (target_user_id, safe_limit)
        else:
            params = (safe_limit,)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        audit_id,
                        audit_action,
                        actor_id,
                        target_user_id::text AS target_user_id,
                        details,
                        action_ts,
                        created_at
                    FROM ae_user_admin_audit
                    {where_sql}
                    ORDER BY action_ts DESC, audit_id DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [self._serialize_audit(row) for row in rows]

