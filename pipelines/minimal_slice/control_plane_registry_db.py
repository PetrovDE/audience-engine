from __future__ import annotations

from .config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_SSLMODE,
    POSTGRES_USER,
)
from .control_plane_registry_domain import normalize_required


def load_psycopg():
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for control-plane registry operations"
        ) from exc
    return psycopg, dict_row


def postgres_conninfo() -> str:
    host = normalize_required(POSTGRES_HOST, field="POSTGRES_HOST")
    db = normalize_required(POSTGRES_DB, field="POSTGRES_DB")
    user = normalize_required(POSTGRES_USER, field="POSTGRES_USER")
    password = normalize_required(POSTGRES_PASSWORD, field="POSTGRES_PASSWORD")
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
