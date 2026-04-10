from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from .control_plane_registry_db import load_psycopg, postgres_conninfo
from .control_plane_registry_domain import (
    UUID_REFERENCE_FIELDS,
    RegistryEntitySpec,
    normalize_required,
    serialize_version_row,
    validate_uuid,
)


class PostgresRegistryRepository:
    def _extra_select_clause(self, spec: RegistryEntitySpec) -> str:
        clauses: list[str] = []
        for field in (
            "model_version_id",
            "feature_set_version_id",
            "policy_version_id",
            "provider_model_ref",
            "capability",
        ):
            if field in spec.exposed_reference_fields:
                clauses.append(
                    f"v.{field}::text AS {field}"
                    if field.endswith("_id")
                    else f"v.{field} AS {field}"
                )
            else:
                clauses.append(f"NULL::text AS {field}")
        return ",\n            ".join(clauses)

    def _fetch_version_by_id(
        self,
        cursor: Any,
        *,
        spec: RegistryEntitySpec,
        version_id: str,
    ) -> dict[str, Any] | None:
        extra_select = self._extra_select_clause(spec)
        cursor.execute(
            f"""
            SELECT
                v.id::text AS version_id,
                r.{spec.root_key_column} AS entity_key,
                v.version,
                v.lifecycle_state,
                v.payload,
                v.created_at,
                v.updated_at,
                v.activated_at,
                {extra_select}
            FROM {spec.version_table} v
            JOIN {spec.root_table} r ON r.id = v.{spec.version_parent_column}
            WHERE v.id = %s::uuid
            """,
            (version_id,),
        )
        row = cursor.fetchone()
        return serialize_version_row(row) if row is not None else None

    def _fetch_version_by_key_and_version(
        self,
        cursor: Any,
        *,
        spec: RegistryEntitySpec,
        entity_key: str,
        version: str,
    ) -> dict[str, Any] | None:
        extra_select = self._extra_select_clause(spec)
        cursor.execute(
            f"""
            SELECT
                v.id::text AS version_id,
                r.{spec.root_key_column} AS entity_key,
                v.version,
                v.lifecycle_state,
                v.payload,
                v.created_at,
                v.updated_at,
                v.activated_at,
                {extra_select}
            FROM {spec.version_table} v
            JOIN {spec.root_table} r ON r.id = v.{spec.version_parent_column}
            WHERE r.{spec.root_key_column} = %s
              AND v.version = %s
            ORDER BY v.created_at DESC
            LIMIT 1
            """,
            (entity_key, version),
        )
        row = cursor.fetchone()
        return serialize_version_row(row) if row is not None else None

    def create_draft_version(
        self,
        *,
        spec: RegistryEntitySpec,
        entity_key: str,
        version: str,
        metadata: dict[str, Any],
        references: dict[str, Any],
    ) -> dict[str, Any]:
        insert_fields: list[str] = []
        insert_params: list[Any] = []
        for field in spec.required_reference_fields:
            raw = references.get(field)
            if raw is None:
                raise ValueError(f"Missing required reference field: {field}")
            value = str(raw)
            value = (
                validate_uuid(value, field=field)
                if field in UUID_REFERENCE_FIELDS
                else normalize_required(value, field=field)
            )
            insert_fields.append(field)
            insert_params.append(value)

        for field in spec.optional_reference_fields:
            raw = references.get(field)
            if raw is None:
                continue
            value = str(raw)
            value = (
                validate_uuid(value, field=field)
                if field in UUID_REFERENCE_FIELDS
                else normalize_required(value, field=field)
            )
            insert_fields.append(field)
            insert_params.append(value)

        root_id = str(uuid4())
        version_id = str(uuid4())
        psycopg, dict_row = load_psycopg()
        with psycopg.connect(postgres_conninfo(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id::text AS id
                    FROM {spec.root_table}
                    WHERE {spec.root_key_column} = %s
                    """,
                    (entity_key,),
                )
                existing_root = cur.fetchone()
                if existing_root is not None:
                    root_id = str(existing_root["id"])
                else:
                    cur.execute(
                        f"""
                        INSERT INTO {spec.root_table} (
                            id,
                            {spec.root_key_column},
                            metadata
                        )
                        VALUES (%s::uuid, %s, %s::jsonb)
                        """,
                        (root_id, entity_key, json.dumps({})),
                    )

                extra_columns = ", ".join(insert_fields)
                extra_placeholders = ", ".join(
                    "%s::uuid" if field in UUID_REFERENCE_FIELDS else "%s"
                    for field in insert_fields
                )
                extra_section = f", {extra_columns}" if extra_columns else ""
                extra_values = f", {extra_placeholders}" if extra_placeholders else ""
                cur.execute(
                    f"""
                    INSERT INTO {spec.version_table} (
                        id,
                        {spec.version_parent_column},
                        version,
                        lifecycle_state,
                        payload
                        {extra_section}
                    )
                    VALUES (
                        %s::uuid,
                        %s::uuid,
                        %s,
                        'draft',
                        %s::jsonb
                        {extra_values}
                    )
                    """,
                    (
                        version_id,
                        root_id,
                        version,
                        json.dumps(metadata),
                        *insert_params,
                    ),
                )
                conn.commit()
                created = self._fetch_version_by_id(
                    cur,
                    spec=spec,
                    version_id=version_id,
                )
                if created is None:
                    raise RuntimeError("Failed to load created draft version")
                return created

    def find_version(
        self,
        *,
        spec: RegistryEntitySpec,
        entity_key: str,
        version: str,
    ) -> dict[str, Any] | None:
        psycopg, dict_row = load_psycopg()
        with psycopg.connect(postgres_conninfo(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                return self._fetch_version_by_key_and_version(
                    cur,
                    spec=spec,
                    entity_key=entity_key,
                    version=version,
                )

    def get_version_by_id(
        self,
        *,
        spec: RegistryEntitySpec,
        version_id: str,
    ) -> dict[str, Any] | None:
        psycopg, dict_row = load_psycopg()
        with psycopg.connect(postgres_conninfo(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                return self._fetch_version_by_id(cur, spec=spec, version_id=version_id)

    def list_versions(
        self,
        *,
        spec: RegistryEntitySpec,
        entity_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        psycopg, dict_row = load_psycopg()
        extra_select = self._extra_select_clause(spec)
        resolved_key = entity_key.strip() if isinstance(entity_key, str) else ""
        with psycopg.connect(postgres_conninfo(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                where = ""
                params: tuple[Any, ...]
                if resolved_key:
                    where = f"WHERE r.{spec.root_key_column} = %s"
                    params = (resolved_key, limit)
                else:
                    params = (limit,)
                cur.execute(
                    f"""
                    SELECT
                        v.id::text AS version_id,
                        r.{spec.root_key_column} AS entity_key,
                        v.version,
                        v.lifecycle_state,
                        v.payload,
                        v.created_at,
                        v.updated_at,
                        v.activated_at,
                        {extra_select}
                    FROM {spec.version_table} v
                    JOIN {spec.root_table} r ON r.id = v.{spec.version_parent_column}
                    {where}
                    ORDER BY v.created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [serialize_version_row(row) for row in rows]

    def get_active_version(
        self,
        *,
        spec: RegistryEntitySpec,
        entity_key: str | None,
    ) -> dict[str, Any] | None:
        psycopg, dict_row = load_psycopg()
        extra_select = self._extra_select_clause(spec)
        resolved_key = entity_key.strip() if isinstance(entity_key, str) else ""
        with psycopg.connect(postgres_conninfo(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                where = "WHERE v.lifecycle_state = 'active'"
                params: tuple[Any, ...] = ()
                if resolved_key:
                    where += f" AND r.{spec.root_key_column} = %s"
                    params = (resolved_key,)
                cur.execute(
                    f"""
                    SELECT
                        v.id::text AS version_id,
                        r.{spec.root_key_column} AS entity_key,
                        v.version,
                        v.lifecycle_state,
                        v.payload,
                        v.created_at,
                        v.updated_at,
                        v.activated_at,
                        {extra_select}
                    FROM {spec.version_table} v
                    JOIN {spec.root_table} r ON r.id = v.{spec.version_parent_column}
                    {where}
                    ORDER BY v.activated_at DESC NULLS LAST, v.created_at DESC
                    LIMIT 1
                    """,
                    params,
                )
                row = cur.fetchone()
        return serialize_version_row(row) if row is not None else None

    def transition_version_state(
        self,
        *,
        spec: RegistryEntitySpec,
        version_id: str,
        target_state: str,
    ) -> dict[str, Any] | None:
        psycopg, dict_row = load_psycopg()
        with psycopg.connect(postgres_conninfo(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {spec.version_table}
                    SET
                        lifecycle_state = %s,
                        updated_at = NOW(),
                        activated_at = CASE
                            WHEN %s = 'active' THEN NOW()
                            ELSE activated_at
                        END
                    WHERE id = %s::uuid
                    """,
                    (target_state, target_state, version_id),
                )
                conn.commit()
                return self._fetch_version_by_id(cur, spec=spec, version_id=version_id)
