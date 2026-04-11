from __future__ import annotations

from typing import Any

from .control_plane_registry_db import load_psycopg, postgres_conninfo
from .user_admin_schema import ensure_user_admin_schema


def _iso_timestamp(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class PostgresUserCredentialsRepository:
    def _connect(self):
        ensure_user_admin_schema()
        psycopg, dict_row = load_psycopg()
        return psycopg.connect(postgres_conninfo(), row_factory=dict_row)

    def _serialize_credential(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": str(row["user_id"]),
            "password_hash": str(row["password_hash"]),
            "require_password_reset": bool(row["require_password_reset"]),
            "password_updated_by": str(row["password_updated_by"]),
            "password_updated_at": _iso_timestamp(row.get("password_updated_at")),
            "created_at": _iso_timestamp(row.get("created_at")),
            "updated_at": _iso_timestamp(row.get("updated_at")),
        }

    def upsert_password_hash(
        self,
        *,
        user_id: str,
        password_hash: str,
        password_updated_by: str,
        require_password_reset: bool,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ae_user_credentials (
                        user_id,
                        password_hash,
                        require_password_reset,
                        password_updated_by,
                        password_updated_at,
                        updated_at
                    )
                    VALUES (
                        %s::uuid,
                        %s,
                        %s,
                        %s,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        password_hash = EXCLUDED.password_hash,
                        require_password_reset = EXCLUDED.require_password_reset,
                        password_updated_by = EXCLUDED.password_updated_by,
                        password_updated_at = NOW(),
                        updated_at = NOW()
                    RETURNING
                        user_id::text AS user_id,
                        password_hash,
                        require_password_reset,
                        password_updated_by,
                        password_updated_at,
                        created_at,
                        updated_at
                    """,
                    (
                        user_id,
                        password_hash,
                        require_password_reset,
                        password_updated_by,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Failed to upsert user credentials.")
        return self._serialize_credential(row)

    def get_credentials_by_user_id(self, *, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        user_id::text AS user_id,
                        password_hash,
                        require_password_reset,
                        password_updated_by,
                        password_updated_at,
                        created_at,
                        updated_at
                    FROM ae_user_credentials
                    WHERE user_id = %s::uuid
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._serialize_credential(row)

