from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import EMBEDDINGS_PATH
from .lifecycle_audit import list_lifecycle_actions, record_lifecycle_action
from .qdrant_index import (
    get_latest_generation,
    list_generation_history,
    promote_latest_generation,
    rollback_latest_alias,
    validate_latest_generation,
)


@dataclass(frozen=True)
class LifecycleActor:
    role: str
    actor_id: str


def build_system_actor(source: str) -> LifecycleActor:
    token = source.strip().replace(" ", "_")
    if not token:
        raise ValueError("System actor source must be a non-empty string")
    return LifecycleActor(role="system_internal", actor_id=f"system:{token}")


def _audit_failure_details(
    exc: Exception, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload = {"error": str(exc)}
    if extra:
        payload.update(extra)
    return payload


def validate_latest(
    *,
    actor: LifecycleActor,
    embeddings_path: Path = EMBEDDINGS_PATH,
) -> dict[str, Any]:
    latest = get_latest_generation(status="built")
    alias_name = latest["alias_name"] if latest else "unknown"
    collection_name = latest["collection_name"] if latest else None
    try:
        result = validate_latest_generation(embeddings_path=embeddings_path)
    except Exception as exc:
        record_lifecycle_action(
            action="validate_generation",
            alias_name=alias_name,
            target_collection_name=collection_name,
            previous_collection_name=None,
            actor_role=actor.role,
            actor_id=actor.actor_id,
            outcome="failed",
            details=_audit_failure_details(exc),
        )
        raise

    record_lifecycle_action(
        action="validate_generation",
        alias_name=result["alias"],
        target_collection_name=result["collection"],
        previous_collection_name=None,
        actor_role=actor.role,
        actor_id=actor.actor_id,
        outcome="success",
        details=result,
    )
    return result


def promote_latest(*, actor: LifecycleActor) -> dict[str, Any]:
    latest = get_latest_generation(status="validated")
    alias_name = latest["alias_name"] if latest else "unknown"
    collection_name = latest["collection_name"] if latest else None
    try:
        result = promote_latest_generation()
    except Exception as exc:
        record_lifecycle_action(
            action="promote_alias",
            alias_name=alias_name,
            target_collection_name=collection_name,
            previous_collection_name=None,
            actor_role=actor.role,
            actor_id=actor.actor_id,
            outcome="failed",
            details=_audit_failure_details(exc),
        )
        raise

    record_lifecycle_action(
        action="promote_alias",
        alias_name=result["alias"],
        target_collection_name=result["collection"],
        previous_collection_name=result.get("previous_collection"),
        actor_role=actor.role,
        actor_id=actor.actor_id,
        outcome="success",
        details=result,
    )
    return result


def rollback_latest(*, actor: LifecycleActor) -> dict[str, Any]:
    latest = get_latest_generation(status="promoted")
    alias_name = latest["alias_name"] if latest else "unknown"
    collection_name = latest["collection_name"] if latest else None
    previous_collection = latest["previous_collection_name"] if latest else None
    try:
        result = rollback_latest_alias()
    except Exception as exc:
        record_lifecycle_action(
            action="rollback_alias",
            alias_name=alias_name,
            target_collection_name=collection_name,
            previous_collection_name=previous_collection,
            actor_role=actor.role,
            actor_id=actor.actor_id,
            outcome="failed",
            details=_audit_failure_details(exc),
        )
        raise

    record_lifecycle_action(
        action="rollback_alias",
        alias_name=result["alias"],
        target_collection_name=result["collection"],
        previous_collection_name=result.get("rolled_back_from"),
        actor_role=actor.role,
        actor_id=actor.actor_id,
        outcome="success",
        details=result,
    )
    return result


def get_generation_status(
    *,
    status: str | None = None,
    alias_name: str | None = None,
) -> dict[str, Any] | None:
    return get_latest_generation(status=status, alias_name=alias_name)


def list_generations(
    *,
    limit: int = 50,
    status: str | None = None,
    alias_name: str | None = None,
) -> list[dict[str, Any]]:
    return list_generation_history(limit=limit, status=status, alias_name=alias_name)


def list_lifecycle_audit(
    *,
    limit: int = 50,
    alias_name: str | None = None,
) -> list[dict[str, Any]]:
    return list_lifecycle_actions(limit=limit, alias_name=alias_name)
