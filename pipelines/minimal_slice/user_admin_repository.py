from __future__ import annotations

from typing import Any
from uuid import uuid4

from .control_plane_registry_db import load_psycopg, postgres_conninfo
from .user_admin_schema import ensure_user_admin_schema


def _iso_timestamp(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _normalize_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


class PostgresUserAdminRepository:
    def _connect(self):
        ensure_user_admin_schema()
        psycopg, dict_row = load_psycopg()
        return psycopg.connect(postgres_conninfo(), row_factory=dict_row)

    def _fetch_roles(self, cursor: Any, *, user_id: str) -> tuple[str, ...]:
        cursor.execute(
            """
            SELECT role
            FROM ae_user_role_assignments
            WHERE user_id = %s::uuid
            ORDER BY role
            """,
            (user_id,),
        )
        return tuple(str(row["role"]) for row in cursor.fetchall())

    def _serialize_user(
        self,
        row: dict[str, Any],
        *,
        roles: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "user_id": str(row["user_id"]),
            "username": str(row["username"]),
            "display_name": str(row["display_name"]),
            "email": _normalize_optional_email(row.get("email")),
            "is_active": bool(row["is_active"]),
            "created_by": str(row["created_by"]),
            "updated_by": str(row["updated_by"]),
            "created_at": _iso_timestamp(row.get("created_at")),
            "updated_at": _iso_timestamp(row.get("updated_at")),
            "roles": roles,
        }

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        email: str | None,
        is_active: bool,
        actor_id: str,
    ) -> dict[str, Any]:
        user_id = str(uuid4())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ae_users (
                        user_id,
                        username,
                        display_name,
                        email,
                        is_active,
                        created_by,
                        updated_by
                    )
                    VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        user_id::text AS user_id,
                        username,
                        display_name,
                        email,
                        is_active,
                        created_by,
                        updated_by,
                        created_at,
                        updated_at
                    """,
                    (
                        user_id,
                        username,
                        display_name,
                        _normalize_optional_email(email),
                        is_active,
                        actor_id,
                        actor_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Failed to create user row.")
        return self._serialize_user(row, roles=())

    def list_users(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        where_sql = "" if include_inactive else "WHERE is_active = TRUE"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        user_id::text AS user_id,
                        username,
                        display_name,
                        email,
                        is_active,
                        created_by,
                        updated_by,
                        created_at,
                        updated_at
                    FROM ae_users
                    {where_sql}
                    ORDER BY created_at DESC, username ASC
                    """
                )
                rows = cur.fetchall()
                return [
                    self._serialize_user(
                        row,
                        roles=self._fetch_roles(cur, user_id=str(row["user_id"])),
                    )
                    for row in rows
                ]

    def get_user_by_id(self, *, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        user_id::text AS user_id,
                        username,
                        display_name,
                        email,
                        is_active,
                        created_by,
                        updated_by,
                        created_at,
                        updated_at
                    FROM ae_users
                    WHERE user_id = %s::uuid
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                roles = self._fetch_roles(cur, user_id=user_id)
                return self._serialize_user(row, roles=roles)

    def get_user_by_username(self, *, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        user_id::text AS user_id,
                        username,
                        display_name,
                        email,
                        is_active,
                        created_by,
                        updated_by,
                        created_at,
                        updated_at
                    FROM ae_users
                    WHERE username = %s
                    """,
                    (username,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                roles = self._fetch_roles(cur, user_id=str(row["user_id"]))
                return self._serialize_user(row, roles=roles)

    def update_user_profile(
        self,
        *,
        user_id: str,
        display_name: str | None,
        email: str | None,
        actor_id: str,
    ) -> dict[str, Any] | None:
        assignments: list[str] = []
        params: list[Any] = []
        if display_name is not None:
            assignments.append("display_name = %s")
            params.append(display_name)
        if email is not None:
            assignments.append("email = %s")
            params.append(_normalize_optional_email(email))
        assignments.extend(["updated_by = %s", "updated_at = NOW()"])
        params.append(actor_id)
        params.append(user_id)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE ae_users
                    SET {", ".join(assignments)}
                    WHERE user_id = %s::uuid
                    RETURNING
                        user_id::text AS user_id,
                        username,
                        display_name,
                        email,
                        is_active,
                        created_by,
                        updated_by,
                        created_at,
                        updated_at
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                roles = self._fetch_roles(cur, user_id=user_id)
            conn.commit()
        return self._serialize_user(row, roles=roles)

    def set_user_active(
        self,
        *,
        user_id: str,
        is_active: bool,
        actor_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ae_users
                    SET is_active = %s, updated_by = %s, updated_at = NOW()
                    WHERE user_id = %s::uuid
                    RETURNING
                        user_id::text AS user_id,
                        username,
                        display_name,
                        email,
                        is_active,
                        created_by,
                        updated_by,
                        created_at,
                        updated_at
                    """,
                    (is_active, actor_id, user_id),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                roles = self._fetch_roles(cur, user_id=user_id)
            conn.commit()
        return self._serialize_user(row, roles=roles)

    def list_user_roles(self, *, user_id: str) -> tuple[str, ...]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._fetch_roles(cur, user_id=user_id)

    def assign_role(
        self,
        *,
        user_id: str,
        role: str,
        actor_id: str,
    ) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ae_user_role_assignments (
                        user_id,
                        role,
                        assigned_by
                    )
                    VALUES (%s::uuid, %s, %s)
                    ON CONFLICT (user_id, role) DO NOTHING
                    """,
                    (user_id, role, actor_id),
                )
                inserted = cur.rowcount > 0
                if inserted:
                    cur.execute(
                        """
                        UPDATE ae_users
                        SET updated_by = %s, updated_at = NOW()
                        WHERE user_id = %s::uuid
                        """,
                        (actor_id, user_id),
                    )
            conn.commit()
        return inserted

    def remove_role(
        self,
        *,
        user_id: str,
        role: str,
        actor_id: str,
    ) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM ae_user_role_assignments
                    WHERE user_id = %s::uuid
                      AND role = %s
                    """,
                    (user_id, role),
                )
                removed = cur.rowcount > 0
                if removed:
                    cur.execute(
                        """
                        UPDATE ae_users
                        SET updated_by = %s, updated_at = NOW()
                        WHERE user_id = %s::uuid
                        """,
                        (actor_id, user_id),
                    )
            conn.commit()
        return removed
