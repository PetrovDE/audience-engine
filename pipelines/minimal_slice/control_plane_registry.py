from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from .config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_SSLMODE,
    POSTGRES_USER,
)

LIFECYCLE_STATES = ("draft", "validated", "active", "deprecated", "retired")
_VALID_LIFECYCLE_STATES = set(LIFECYCLE_STATES)
_ALLOWED_STATE_TRANSITIONS = {
    "draft": {"validated"},
    "validated": {"draft", "active"},
    "active": {"deprecated"},
    "deprecated": {"active", "retired"},
    "retired": set(),
}


@dataclass(frozen=True)
class RegistryEntitySpec:
    root_table: str
    version_table: str
    root_key_column: str
    version_parent_column: str
    required_reference_fields: tuple[str, ...]
    optional_reference_fields: tuple[str, ...]
    exposed_reference_fields: tuple[str, ...]


_ENTITY_SPECS: dict[str, RegistryEntitySpec] = {
    "feature_sets": RegistryEntitySpec(
        root_table="feature_sets",
        version_table="feature_set_versions",
        root_key_column="feature_set_key",
        version_parent_column="feature_set_id",
        required_reference_fields=(),
        optional_reference_fields=(),
        exposed_reference_fields=(),
    ),
    "models": RegistryEntitySpec(
        root_table="models",
        version_table="model_versions",
        root_key_column="model_key",
        version_parent_column="model_id",
        required_reference_fields=(),
        optional_reference_fields=(),
        exposed_reference_fields=(),
    ),
    "embedding_providers": RegistryEntitySpec(
        root_table="embedding_providers",
        version_table="embedding_model_versions",
        root_key_column="provider_key",
        version_parent_column="embedding_provider_id",
        required_reference_fields=("model_version_id", "provider_model_ref"),
        optional_reference_fields=("capability",),
        exposed_reference_fields=(
            "model_version_id",
            "provider_model_ref",
            "capability",
        ),
    ),
    "policies": RegistryEntitySpec(
        root_table="policies",
        version_table="policy_versions",
        root_key_column="policy_key",
        version_parent_column="policy_id",
        required_reference_fields=(),
        optional_reference_fields=(),
        exposed_reference_fields=(),
    ),
    "audience_definitions": RegistryEntitySpec(
        root_table="audience_definitions",
        version_table="audience_definition_versions",
        root_key_column="audience_definition_key",
        version_parent_column="audience_definition_id",
        required_reference_fields=("feature_set_version_id",),
        optional_reference_fields=("policy_version_id",),
        exposed_reference_fields=("feature_set_version_id", "policy_version_id"),
    ),
}

_UUID_REFERENCE_FIELDS = {
    "model_version_id",
    "feature_set_version_id",
    "policy_version_id",
    "audience_definition_version_id",
    "embedding_model_version_id",
}


def _psycopg():
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for control-plane registry operations"
        ) from exc
    return psycopg, dict_row


def _normalize_required(value: str, *, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{field} is required")
    return resolved


def _postgres_conninfo() -> str:
    host = _normalize_required(POSTGRES_HOST, field="POSTGRES_HOST")
    db = _normalize_required(POSTGRES_DB, field="POSTGRES_DB")
    user = _normalize_required(POSTGRES_USER, field="POSTGRES_USER")
    password = _normalize_required(POSTGRES_PASSWORD, field="POSTGRES_PASSWORD")
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


def _validate_uuid(value: str, *, field: str) -> str:
    candidate = _normalize_required(value, field=field)
    try:
        UUID(candidate)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID: {candidate!r}") from exc
    return candidate


def _entity_spec(entity_type: str) -> RegistryEntitySpec:
    key = _normalize_required(entity_type, field="entity_type").lower()
    spec = _ENTITY_SPECS.get(key)
    if spec is None:
        supported = ", ".join(sorted(_ENTITY_SPECS))
        raise ValueError(
            f"Unsupported entity_type: {entity_type}. Supported: {supported}"
        )
    return spec


def validate_lifecycle_transition(current_state: str, target_state: str) -> None:
    current = _normalize_required(current_state, field="current_state").lower()
    target = _normalize_required(target_state, field="target_state").lower()
    if current not in _VALID_LIFECYCLE_STATES:
        raise ValueError(f"Unknown current_state: {current_state}")
    if target not in _VALID_LIFECYCLE_STATES:
        raise ValueError(f"Unknown target_state: {target_state}")
    if current == target:
        return
    allowed = _ALLOWED_STATE_TRANSITIONS[current]
    if target not in allowed:
        raise ValueError(f"Invalid lifecycle transition: {current} -> {target}")


def _serialize_version_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}

    def _to_iso(ts: Any) -> str | None:
        return ts.isoformat() if isinstance(ts, datetime) else None

    result: dict[str, Any] = {
        "version_id": str(row["version_id"]),
        "entity_key": str(row["entity_key"]),
        "version": str(row["version"]),
        "lifecycle_state": str(row["lifecycle_state"]),
        "payload": payload,
        "created_at": _to_iso(row.get("created_at")),
        "updated_at": _to_iso(row.get("updated_at")),
        "activated_at": _to_iso(row.get("activated_at")),
    }
    for field in (
        "model_version_id",
        "feature_set_version_id",
        "policy_version_id",
        "provider_model_ref",
        "capability",
    ):
        if field in row and row[field] is not None:
            result[field] = str(row[field])
    return result


def _extra_select_clause(spec: RegistryEntitySpec) -> str:
    clauses: list[str] = []
    for field in (
        "model_version_id",
        "feature_set_version_id",
        "policy_version_id",
        "provider_model_ref",
        "capability",
    ):
        if field in spec.exposed_reference_fields:
            if field.endswith("_id"):
                clauses.append(f"v.{field}::text AS {field}")
            else:
                clauses.append(f"v.{field} AS {field}")
        else:
            clauses.append(f"NULL::text AS {field}")
    return ",\n            ".join(clauses)


def _fetch_version_by_id(
    cursor: Any,
    *,
    spec: RegistryEntitySpec,
    version_id: str,
) -> dict[str, Any] | None:
    extra_select = _extra_select_clause(spec)
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
    if row is None:
        return None
    return _serialize_version_row(row)


def create_draft_version(
    *,
    entity_type: str,
    entity_key: str,
    version: str,
    metadata: dict[str, Any] | None = None,
    references: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _entity_spec(entity_type)
    resolved_key = _normalize_required(entity_key, field="entity_key")
    resolved_version = _normalize_required(version, field="version")
    payload = metadata if isinstance(metadata, dict) else {}
    ref_values = references if isinstance(references, dict) else {}

    insert_fields: list[str] = []
    insert_params: list[Any] = []
    for field in spec.required_reference_fields:
        raw = ref_values.get(field)
        if raw is None:
            raise ValueError(f"Missing required reference field: {field}")
        value = str(raw)
        if field in _UUID_REFERENCE_FIELDS:
            value = _validate_uuid(value, field=field)
        else:
            value = _normalize_required(value, field=field)
        insert_fields.append(field)
        insert_params.append(value)

    for field in spec.optional_reference_fields:
        raw = ref_values.get(field)
        if raw is None:
            continue
        value = str(raw)
        if field in _UUID_REFERENCE_FIELDS:
            value = _validate_uuid(value, field=field)
        else:
            value = _normalize_required(value, field=field)
        insert_fields.append(field)
        insert_params.append(value)

    root_id = str(uuid4())
    version_id = str(uuid4())

    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id::text AS id
                FROM {spec.root_table}
                WHERE {spec.root_key_column} = %s
                """,
                (resolved_key,),
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
                    (root_id, resolved_key, json.dumps({})),
                )

            extra_columns = ", ".join(insert_fields)
            extra_placeholders = ", ".join(
                [
                    "%s::uuid" if field in _UUID_REFERENCE_FIELDS else "%s"
                    for field in insert_fields
                ]
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
                    resolved_version,
                    json.dumps(payload),
                    *insert_params,
                ),
            )
            conn.commit()

            created = _fetch_version_by_id(cur, spec=spec, version_id=version_id)
            if created is None:
                raise RuntimeError("Failed to load created draft version")
            return created


def list_versions(
    *,
    entity_type: str,
    entity_key: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    spec = _entity_spec(entity_type)
    resolved_key = entity_key.strip() if isinstance(entity_key, str) else ""

    psycopg, dict_row = _psycopg()
    extra_select = _extra_select_clause(spec)
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if resolved_key:
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
                    WHERE r.{spec.root_key_column} = %s
                    ORDER BY v.created_at DESC
                    LIMIT %s
                    """,
                    (resolved_key, limit),
                )
            else:
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
                    ORDER BY v.created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    return [_serialize_version_row(row) for row in rows]


def get_active_version(
    *,
    entity_type: str,
    entity_key: str | None = None,
) -> dict[str, Any] | None:
    spec = _entity_spec(entity_type)
    resolved_key = entity_key.strip() if isinstance(entity_key, str) else ""

    psycopg, dict_row = _psycopg()
    extra_select = _extra_select_clause(spec)
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if resolved_key:
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
                    WHERE v.lifecycle_state = 'active'
                      AND r.{spec.root_key_column} = %s
                    ORDER BY v.activated_at DESC NULLS LAST, v.created_at DESC
                    LIMIT 1
                    """,
                    (resolved_key,),
                )
            else:
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
                    WHERE v.lifecycle_state = 'active'
                    ORDER BY v.activated_at DESC NULLS LAST, v.created_at DESC
                    LIMIT 1
                    """
                )
            row = cur.fetchone()
    if row is None:
        return None
    return _serialize_version_row(row)


def transition_version_state(
    *,
    entity_type: str,
    version_id: str,
    target_state: str,
) -> dict[str, Any]:
    spec = _entity_spec(entity_type)
    resolved_version_id = _validate_uuid(version_id, field="version_id")
    resolved_target = _normalize_required(target_state, field="target_state").lower()

    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            current = _fetch_version_by_id(
                cur, spec=spec, version_id=resolved_version_id
            )
            if current is None:
                raise ValueError(
                    f"Version not found for entity_type={entity_type}: {version_id}"
                )
            validate_lifecycle_transition(current["lifecycle_state"], resolved_target)
            if current["lifecycle_state"] == resolved_target:
                return current

            try:
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
                    (resolved_target, resolved_target, resolved_version_id),
                )
                conn.commit()
            except Exception as exc:
                if resolved_target == "active":
                    raise ValueError(
                        "Activation failed. Another active version may already exist "
                        "for this entity."
                    ) from exc
                raise

            updated = _fetch_version_by_id(
                cur,
                spec=spec,
                version_id=resolved_version_id,
            )
            if updated is None:
                raise RuntimeError(
                    "Version disappeared after lifecycle transition update"
                )
            return updated


def _resolve_explicit_or_active_version_id(
    cursor: Any,
    *,
    table: str,
    explicit_id: str | None,
    expected_version: str | None = None,
    parent_field: str | None = None,
    parent_id: str | None = None,
) -> str | None:
    if explicit_id:
        resolved_id = _validate_uuid(explicit_id, field=f"{table}.id")
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
    if row is None:
        return None
    return str(row["id"])


def resolve_run_lineage_binding(
    *,
    fs_version: str,
    model_version: str,
    policy_version: str,
    feature_set_version_id: str | None = None,
    model_version_id: str | None = None,
    embedding_model_version_id: str | None = None,
    policy_version_id: str | None = None,
    audience_definition_version_id: str | None = None,
) -> dict[str, str | None]:
    psycopg, dict_row = _psycopg()
    with psycopg.connect(_postgres_conninfo(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            resolved_feature_set_version_id = _resolve_explicit_or_active_version_id(
                cur,
                table="feature_set_versions",
                explicit_id=feature_set_version_id,
                expected_version=fs_version,
            )
            resolved_model_version_id = _resolve_explicit_or_active_version_id(
                cur,
                table="model_versions",
                explicit_id=model_version_id,
                expected_version=model_version,
            )
            resolved_policy_version_id = _resolve_explicit_or_active_version_id(
                cur,
                table="policy_versions",
                explicit_id=policy_version_id,
                expected_version=policy_version,
            )
            resolved_embedding_model_version_id = (
                _resolve_explicit_or_active_version_id(
                    cur,
                    table="embedding_model_versions",
                    explicit_id=embedding_model_version_id,
                    parent_field="model_version_id",
                    parent_id=resolved_model_version_id,
                )
            )
            resolved_audience_definition_version_id = (
                _resolve_explicit_or_active_version_id(
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


def persist_run_lineage_binding(
    cursor: Any,
    *,
    run_id: str,
    feature_set_version_id: str | None,
    model_version_id: str | None,
    embedding_model_version_id: str | None,
    policy_version_id: str | None,
    audience_definition_version_id: str | None,
    delivery_target_id: str | None,
    export_profile_id: str | None,
) -> None:
    resolved_run_id = _validate_uuid(run_id, field="run_id")
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
            resolved_run_id,
            feature_set_version_id,
            model_version_id,
            embedding_model_version_id,
            policy_version_id,
            audience_definition_version_id,
            delivery_target_id,
            export_profile_id,
        ),
    )
