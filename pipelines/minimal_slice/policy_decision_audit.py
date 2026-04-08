from __future__ import annotations

import json
from typing import Any

from pipelines.version_bundle import VersionBundle

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
            "psycopg is required for policy decision audit persistence/read"
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


def build_policy_decision_audit_rows(
    *,
    policy_result: dict[str, Any],
    bundle: VersionBundle,
    resolved_collection: str,
    decision_ts: str,
) -> list[tuple]:
    rows: list[tuple] = []
    for row in policy_result.get("results", []):
        customer_id = str(row.get("customer_id", ""))
        reasons = row.get("reasons", [])
        reason_codes = [
            str(reason.get("reason_code", ""))
            for reason in reasons
            if reason.get("reason_code")
        ]
        explanation = {
            "selected": bool(row.get("selected", False)),
            "score": float(row.get("score", 0.0)),
            "reasons": reasons,
            "details": row.get("explanation", {}),
        }
        rows.append(
            (
                bundle.run_id,
                bundle.campaign_id,
                customer_id,
                str(row.get("decision", "reject")),
                reason_codes,
                bundle.policy_version,
                bundle.fs_version,
                bundle.emb_version,
                bundle.model_version,
                bundle.index_alias,
                resolved_collection,
                decision_ts,
                json.dumps(explanation),
            )
        )
    return rows


def write_policy_decision_audit_rows(cursor: Any, decision_rows: list[tuple]) -> None:
    if not decision_rows:
        return
    cursor.executemany(
        """
        INSERT INTO policy_decision_audit (
            run_id,
            campaign_id,
            customer_id,
            decision,
            reason_codes,
            policy_version,
            fs_version,
            emb_version,
            model_version,
            index_alias,
            index_generation,
            decision_ts,
            decision_explanation
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::jsonb)
        """,
        decision_rows,
    )


def fetch_policy_decision_audit(run_id: str, customer_id: str) -> dict[str, Any] | None:
    with _psycopg().connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    run_id,
                    campaign_id,
                    customer_id,
                    decision,
                    reason_codes,
                    policy_version,
                    fs_version,
                    emb_version,
                    model_version,
                    index_alias,
                    index_generation,
                    decision_ts,
                    decision_explanation
                FROM policy_decision_audit
                WHERE run_id = %s::uuid AND customer_id = %s
                ORDER BY decision_ts DESC, created_at DESC
                LIMIT 1
                """,
                (run_id, customer_id),
            )
            row = cur.fetchone()

    if not row:
        return None

    explanation = row[12]
    if isinstance(explanation, str):
        explanation = json.loads(explanation)

    return {
        "run_id": str(row[0]),
        "campaign_id": row[1],
        "customer_id": row[2],
        "decision": row[3],
        "reason_codes": list(row[4] or []),
        "policy_version": row[5],
        "fs_version": row[6],
        "emb_version": row[7],
        "model_version": row[8],
        "index_alias": row[9],
        "index_generation": row[10],
        "decision_ts": row[11].isoformat() if row[11] is not None else None,
        "explanation": explanation or {},
    }
