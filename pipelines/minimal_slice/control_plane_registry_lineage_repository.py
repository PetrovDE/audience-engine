from __future__ import annotations

from typing import Any

from .control_plane_registry_db import load_psycopg, postgres_conninfo
from .control_plane_registry_domain import validate_uuid


class PostgresLineageBindingRepository:
    def _resolve_explicit_or_active_version_id(
        self,
        cursor: Any,
        *,
        table: str,
        explicit_id: str | None,
        expected_version: str | None = None,
        parent_field: str | None = None,
        parent_id: str | None = None,
    ) -> str | None:
        if explicit_id:
            resolved_id = validate_uuid(explicit_id, field=f"{table}.id")
            cursor.execute(
                f"""
                SELECT id::text AS id, version, lifecycle_state
                FROM {table}
                WHERE id = %s::uuid
                """,
                (resolved_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"{table} id not found: {resolved_id}")
            if str(row["lifecycle_state"]) != "active":
                raise ValueError(f"{table} id is not active: {resolved_id}")
            if expected_version and str(row["version"]) != expected_version:
                raise ValueError(
                    f"{table} version mismatch: expected={expected_version}, "
                    f"actual={row['version']}"
                )
            return str(row["id"])

        query_filters: list[str] = ["lifecycle_state = 'active'"]
        params: list[Any] = []
        if expected_version:
            query_filters.append("version = %s")
            params.append(expected_version)
        if parent_field and parent_id:
            query_filters.append(f"{parent_field} = %s::uuid")
            params.append(parent_id)
        where_clause = " AND ".join(query_filters)
        cursor.execute(
            f"""
            SELECT id::text AS id
            FROM {table}
            WHERE {where_clause}
            ORDER BY activated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            tuple(params),
        )
        row = cursor.fetchone()
        return None if row is None else str(row["id"])

    def resolve_run_lineage_ids(
        self,
        *,
        fs_version: str,
        model_version: str,
        policy_version: str,
        feature_set_version_id: str | None,
        model_version_id: str | None,
        embedding_model_version_id: str | None,
        policy_version_id: str | None,
        audience_definition_version_id: str | None,
    ) -> dict[str, str | None]:
        psycopg, dict_row = load_psycopg()
        with psycopg.connect(postgres_conninfo(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                resolved_feature_set_version_id = (
                    self._resolve_explicit_or_active_version_id(
                        cur,
                        table="feature_set_versions",
                        explicit_id=feature_set_version_id,
                        expected_version=fs_version,
                    )
                )
                resolved_model_version_id = self._resolve_explicit_or_active_version_id(
                    cur,
                    table="model_versions",
                    explicit_id=model_version_id,
                    expected_version=model_version,
                )
                resolved_policy_version_id = (
                    self._resolve_explicit_or_active_version_id(
                        cur,
                        table="policy_versions",
                        explicit_id=policy_version_id,
                        expected_version=policy_version,
                    )
                )
                resolved_embedding_model_version_id = (
                    self._resolve_explicit_or_active_version_id(
                        cur,
                        table="embedding_model_versions",
                        explicit_id=embedding_model_version_id,
                        parent_field="model_version_id",
                        parent_id=resolved_model_version_id,
                    )
                )
                resolved_audience_definition_version_id = (
                    self._resolve_explicit_or_active_version_id(
                        cur,
                        table="audience_definition_versions",
                        explicit_id=audience_definition_version_id,
                        parent_field="feature_set_version_id",
                        parent_id=resolved_feature_set_version_id,
                    )
                )

        return {
            "feature_set_version_id": resolved_feature_set_version_id,
            "model_version_id": resolved_model_version_id,
            "embedding_model_version_id": resolved_embedding_model_version_id,
            "policy_version_id": resolved_policy_version_id,
            "audience_definition_version_id": resolved_audience_definition_version_id,
        }

    def persist_run_lineage_binding(self, cursor: Any, **kwargs: Any) -> None:
        run_id = validate_uuid(str(kwargs["run_id"]), field="run_id")
        cursor.execute(
            """
            INSERT INTO audience_run_lineage_binding (
                run_id,
                feature_set_version_id,
                model_version_id,
                embedding_model_version_id,
                policy_version_id,
                audience_definition_version_id,
                delivery_target_id,
                export_profile_id
            )
            VALUES (
                %s::uuid,
                %s::uuid,
                %s::uuid,
                %s::uuid,
                %s::uuid,
                %s::uuid,
                %s,
                %s
            )
            """,
            (
                run_id,
                kwargs.get("feature_set_version_id"),
                kwargs.get("model_version_id"),
                kwargs.get("embedding_model_version_id"),
                kwargs.get("policy_version_id"),
                kwargs.get("audience_definition_version_id"),
                kwargs.get("delivery_target_id"),
                kwargs.get("export_profile_id"),
            ),
        )
