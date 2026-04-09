import json
import logging
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import yaml

from pipelines.version_bundle import (
    VersionBundle,
    build_version_bundle,
    preflight_version_bundle,
)

from . import control_plane, delivery_runner, integrations, lifecycle_service
from .config import (
    BLACKLIST_PATH,
    COMM_HISTORY_PATH,
    EMBED_SPEC_PATH,
    EMBEDDING_MODEL_VERSION,
    EXPORT_PATH,
    FEATURE_MART_PATH,
    FEATURE_SET_PATH,
    GOVERNANCE_DIR,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    QDRANT_ALIAS,
    RAW_PATH,
    SUMMARY_PATH,
)
from .data_quality import (
    DataQualityError,
    validate_embeddings_artifact,
    validate_feature_mart_contract,
    validate_raw_contract,
)
from .embedding import build_embeddings, read_embeddings_emb_version
from .lifecycle_service import build_system_actor
from .policy_decision_audit import (
    build_policy_decision_audit_rows,
    write_policy_decision_audit_rows,
)
from .policy_engine import evaluate_policy
from .qdrant_index import build_generation
from .retrieval import retrieve_similar
from .synthetic_data import generate_synthetic_data

logger = logging.getLogger(__name__)


def _load_feature_set_version() -> str:
    with FEATURE_SET_PATH.open("r", encoding="utf-8") as f:
        fs = yaml.safe_load(f)
    return fs["fs_version"]


def _build_and_validate_bundle(
    campaign_id: str, *, policy_version: str
) -> VersionBundle:
    bundle = build_version_bundle(
        fs_version=_load_feature_set_version(),
        policy_version=policy_version,
        index_alias=QDRANT_ALIAS,
        campaign_id=campaign_id,
        embedding_spec_path=EMBED_SPEC_PATH,
        model_version=EMBEDDING_MODEL_VERSION,
    )
    preflight_version_bundle(
        bundle=bundle,
        embedding_spec_path=EMBED_SPEC_PATH,
        policy_registry_path=GOVERNANCE_DIR / "policies" / "policy_registry.yaml",
        feature_registry_path=GOVERNANCE_DIR / "features" / "feature_registry.yaml",
        logged_fields={
            "customer_id",
            "fs_version",
            "emb_version",
            "policy_version",
            "is_employee_flag",
            "do_not_contact_flag",
            "customer_tenure_months",
            "delinquency_12m_count",
            "opt_out_flag",
            "legal_suppression_flag",
            "product_line",
            "region_code",
            "segment_id",
        },
        runtime_embedding_model=EMBEDDING_MODEL_VERSION,
    )
    return bundle


def _postgres_conninfo() -> str:
    return (
        f"host={POSTGRES_HOST} "
        f"port={POSTGRES_PORT} "
        f"dbname={POSTGRES_DB} "
        f"user={POSTGRES_USER} "
        f"password={POSTGRES_PASSWORD}"
    )


def _build_audit_rows(
    *,
    retrieved: list[dict],
    policy_result: dict,
    bundle: VersionBundle,
    run_ts: str,
    product_id: str,
    channel: str,
    resolved_collection: str,
    operation_context: dict,
    export_context: dict,
) -> tuple[dict, list[tuple], list[tuple], list[tuple]]:
    ranking: dict[str, tuple[float, int]] = {}
    for idx, row in enumerate(retrieved, start=1):
        customer_id = row.get("customer_id")
        if not customer_id:
            continue
        ranking[customer_id] = (float(row.get("score", 0.0)), idx)

    selected_rows: list[tuple] = []
    selected_customer_ids = {
        row["customer_id"] for row in policy_result.get("selected", [])
    }
    reject_counts: Counter = Counter(policy_result.get("rejection_summary", {}))
    for row in policy_result["results"]:
        customer_id = row["customer_id"]
        if customer_id in selected_customer_ids:
            score, rank = ranking.get(customer_id, (0.0, 0))
            selected_rows.append(
                (bundle.run_id, customer_id, score, rank, channel, run_ts)
            )
            continue

    rejection_rows = [
        (bundle.run_id, reason_code, count, run_ts)
        for reason_code, count in sorted(reject_counts.items())
    ]
    run_row = {
        "run_id": bundle.run_id,
        "campaign_id": bundle.campaign_id,
        "product_id": product_id,
        "run_ts": run_ts,
        "version_bundle": {
            "fs_version": bundle.fs_version,
            "emb_version": bundle.emb_version,
            "model_version": bundle.model_version,
            "policy_version": bundle.policy_version,
            "index_alias": bundle.index_alias,
            "concrete_qdrant_collection": resolved_collection,
            "run_id": bundle.run_id,
            "campaign_id": bundle.campaign_id,
        },
        "parameters": {
            "query_customer_id": "cust_00000",
            "retrieval_top_k": len(retrieved),
            "channel": channel,
            "requested_size": len(selected_rows),
            "policy_rejection_summary": dict(reject_counts),
            "policy_status": policy_result.get("status", "unknown"),
            "operation_context": operation_context,
            "export_context": export_context,
        },
    }
    decision_rows = build_policy_decision_audit_rows(
        policy_result=policy_result,
        bundle=bundle,
        resolved_collection=resolved_collection,
        decision_ts=run_ts,
    )
    return run_row, selected_rows, rejection_rows, decision_rows


def _write_audit_to_postgres(
    *,
    run_row: dict,
    selected_rows: list[tuple],
    rejection_rows: list[tuple],
    decision_rows: list[tuple],
) -> None:
    with psycopg.connect(_postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audience_run (
                    run_id,
                    campaign_id,
                    product_id,
                    run_ts,
                    version_bundle,
                    parameters
                )
                VALUES (%s, %s, %s, %s::timestamptz, %s::jsonb, %s::jsonb)
                """,
                (
                    run_row["run_id"],
                    run_row["campaign_id"],
                    run_row["product_id"],
                    run_row["run_ts"],
                    json.dumps(run_row["version_bundle"]),
                    json.dumps(run_row["parameters"]),
                ),
            )
            if selected_rows:
                cur.executemany(
                    """
                    INSERT INTO audience_run_selected (
                        run_id,
                        customer_id,
                        final_score,
                        rank,
                        channel,
                        selected_ts
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::timestamptz)
                    """,
                    selected_rows,
                )
            if rejection_rows:
                cur.executemany(
                    """
                    INSERT INTO audience_run_rejections_summary (
                        run_id,
                        reason_code,
                        rejected_count,
                        summary_ts
                    )
                    VALUES (%s, %s, %s, %s::timestamptz)
                    """,
                    rejection_rows,
                )
            write_policy_decision_audit_rows(cur, decision_rows)
        conn.commit()


def _build_policy_input(retrieved: list[dict]) -> list[dict]:
    policy_input: list[dict] = []
    for row in retrieved:
        payload = row.get("payload") or {}
        policy_input.append(
            {
                "customer_id": row["customer_id"],
                "score": row.get("score", 0.0),
                "do_not_contact_flag": payload.get("do_not_contact_flag", False),
                "is_employee_flag": payload.get("is_employee_flag", False),
                "customer_tenure_months": payload.get("customer_tenure_months", 0),
                "delinquency_12m_count": payload.get("delinquency_12m_count", 0),
                "opt_out_flag": payload.get("opt_out_flag", False),
                "legal_suppression_flag": payload.get("legal_suppression_flag", False),
            }
        )
    return policy_input


def _write_failure_summary(
    *,
    bundle: VersionBundle,
    run_ts: str,
    quality_checks: list[dict],
    error: DataQualityError,
    operation_context: dict,
) -> dict:
    summary = {
        "run_ts": run_ts,
        "status": "failed",
        "operations": operation_context,
        "versions": {
            "fs_version": bundle.fs_version,
            "emb_version": bundle.emb_version,
            "model_version": bundle.model_version,
            "policy_version": bundle.policy_version,
            "index_alias": bundle.index_alias,
            "concrete_qdrant_collection": bundle.concrete_qdrant_collection,
            "run_id": bundle.run_id,
            "campaign_id": bundle.campaign_id,
        },
        "quality": {
            "status": "failed",
            "checks": quality_checks,
            "error": error.to_dict(),
        },
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


def _append_run_event(
    *,
    summary: dict,
    operation_context: dict,
    trigger_source: str,
) -> None:
    versions = summary.get("versions") if isinstance(summary, dict) else {}
    quality = summary.get("quality") if isinstance(summary, dict) else {}
    export = summary.get("export") if isinstance(summary, dict) else {}
    delivery = summary.get("delivery") if isinstance(summary, dict) else {}
    event = {
        "event_ts": datetime.now(timezone.utc).isoformat(),
        "trigger_source": trigger_source,
        "status": summary.get("status"),
        "run_ts": summary.get("run_ts"),
        "run_id": versions.get("run_id") if isinstance(versions, dict) else None,
        "campaign_id": (
            versions.get("campaign_id") if isinstance(versions, dict) else None
        ),
        "policy_version": (
            versions.get("policy_version") if isinstance(versions, dict) else None
        ),
        "emb_version": versions.get("emb_version")
        if isinstance(versions, dict)
        else None,
        "integration_profile_id": operation_context.get("integration_profile_id"),
        "source_id": operation_context.get("source_id"),
        "export_id": operation_context.get("export_id"),
        "delivery_target_id": operation_context.get("delivery_target_id"),
        "quality_status": quality.get("status") if isinstance(quality, dict) else None,
        "export_status": export.get("status") if isinstance(export, dict) else None,
        "export_uri": export.get("export_uri") if isinstance(export, dict) else None,
        "delivery_status": delivery.get("status")
        if isinstance(delivery, dict)
        else None,
        "delivery_job_id": delivery.get("delivery_job_id")
        if isinstance(delivery, dict)
        else None,
        "error": quality.get("error") if isinstance(quality, dict) else None,
    }
    control_plane.append_run_event(event)


def _append_early_failure_run_event(
    *,
    early_context: dict,
    operation_context: dict,
    failure_stage: str,
    error: Exception,
) -> None:
    event = {
        "event_ts": datetime.now(timezone.utc).isoformat(),
        "trigger_source": "system:run_flow",
        "status": "failed",
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "run_id": None,
        "campaign_id": early_context.get("campaign_id"),
        "policy_version": operation_context.get("policy_version")
        or early_context.get("requested_policy_version"),
        "emb_version": None,
        "integration_profile_id": operation_context.get("integration_profile_id")
        or early_context.get("requested_integration_profile_id"),
        "delivery_target_id": operation_context.get("delivery_target_id")
        or early_context.get("requested_delivery_target_id"),
        "source_id": operation_context.get("source_id"),
        "export_id": operation_context.get("export_id"),
        "quality_status": "failed",
        "export_status": None,
        "export_uri": None,
        "error": {
            "code": "RUN_FAILED_PRECHECK",
            "stage": failure_stage,
            "detail": str(error),
            "requested_size": early_context.get("requested_size"),
            "requested_policy_version": early_context.get("requested_policy_version"),
            "requested_integration_profile_id": early_context.get(
                "requested_integration_profile_id"
            ),
            "requested_delivery_target_id": early_context.get(
                "requested_delivery_target_id"
            ),
            "policy_selection_source": operation_context.get("policy_selection_source"),
            "integration_selection_source": operation_context.get(
                "integration_selection_source"
            ),
            "delivery_selection_source": operation_context.get(
                "delivery_selection_source"
            ),
        },
    }
    try:
        control_plane.append_run_event(event)
    except Exception as event_exc:  # pragma: no cover - best-effort logging path
        logger.error("Failed to append early failure run event: %s", event_exc)


def run_minimal_vertical_slice(
    campaign_id: str | None = None,
    *,
    policy_version: str | None = None,
    integration_profile_id: str | None = None,
    delivery_target_id: str | None = None,
    requested_size: int = 20,
) -> dict:
    early_context = {
        "campaign_id": campaign_id,
        "requested_policy_version": policy_version,
        "requested_integration_profile_id": integration_profile_id,
        "requested_delivery_target_id": delivery_target_id,
        "requested_size": requested_size,
    }
    operation_context: dict = {}
    bundle: VersionBundle | None = None
    failure_stage = "resolve_run_configuration"
    quality_checks: list[dict] = []
    try:
        run_config = control_plane.resolve_run_configuration(
            policy_version=policy_version,
            integration_profile_id=integration_profile_id,
            delivery_target_id=delivery_target_id,
        )
        operation_context = {
            "policy_version": run_config.policy_version,
            "policy_selection_source": run_config.policy_selection_source,
            "integration_profile_id": run_config.integration_profile_id,
            "integration_selection_source": run_config.integration_selection_source,
            "delivery_target_id": run_config.delivery_target_id,
            "delivery_selection_source": run_config.delivery_selection_source,
            "source_id": run_config.source_id,
            "export_id": run_config.export_id,
            "requested_size": requested_size,
        }
        failure_stage = "build_version_bundle_preflight"
        bundle = _build_and_validate_bundle(
            campaign_id=campaign_id or str(uuid4()),
            policy_version=run_config.policy_version,
        )
        failure_stage = "run_pipeline"
        generated = generate_synthetic_data(customer_count=200, seed=7)
        quality_checks.append(validate_raw_contract(generated["raw"]))

        feature_mart_path, integration_meta = (
            integrations.build_feature_mart_for_profile(
                raw_path=generated["raw"],
                output_path=FEATURE_MART_PATH,
                profile_id=run_config.integration_profile_id,
                run_id=bundle.run_id,
            )
        )
        operation_context.update(integration_meta)
        quality_checks.append(validate_feature_mart_contract(feature_mart_path))

        embeddings_path, vector_size = build_embeddings(
            feature_mart_path=feature_mart_path,
            ollama_model=EMBEDDING_MODEL_VERSION,
        )
        quality_checks.append(
            validate_embeddings_artifact(
                embeddings_path=embeddings_path,
                expected_emb_version=bundle.emb_version,
            )
        )
        runtime_emb_version = read_embeddings_emb_version(embeddings_path)
        if runtime_emb_version != bundle.emb_version:
            raise ValueError(
                "Embedding lineage mismatch at runtime: "
                f"bundle.emb_version={bundle.emb_version!r}, "
                f"runtime.emb_version={runtime_emb_version!r}"
            )
        build_generation(
            embeddings_path=embeddings_path,
            vector_size=vector_size,
            alias_name_override=bundle.index_alias,
            collection_name_override=bundle.concrete_qdrant_collection,
        )
        system_actor = build_system_actor("run_flow")
        lifecycle_service.validate_latest(
            actor=system_actor,
            embeddings_path=embeddings_path,
        )
        index_meta = lifecycle_service.promote_latest(
            actor=system_actor,
        )

        query_customer = "cust_00000"
        retrieved = retrieve_similar(
            top_k=50,
            query_customer_id=query_customer,
            product_line="credit_card",
            region_codes=["us_west", "us_central", "us_east"],
            segment_ids=["mass", "affluent", "student", "smb"],
            min_tenure_months=3,
            max_delinquency_12m_count=2,
            fs_version=bundle.fs_version,
            emb_version=bundle.emb_version,
            policy_version=bundle.policy_version,
        )
        policy_input = _build_policy_input(retrieved)
        policy_result = evaluate_policy(
            candidates=policy_input,
            policy_version=bundle.policy_version,
            blacklist_path=BLACKLIST_PATH,
            comm_history_path=COMM_HISTORY_PATH,
            campaign_id=bundle.campaign_id,
            requested_size=requested_size,
        )
        run_ts = datetime.now(timezone.utc).isoformat()
        export_ready = {
            **policy_result,
            "results": [
                row for row in policy_result["results"] if row.get("selected", False)
            ],
        }
        pre_export_audit_context = {
            "status": "pending",
            "delivery_target_id": run_config.delivery_target_id,
        }
        run_row, selected_rows, rejection_rows, decision_rows = _build_audit_rows(
            retrieved=retrieved,
            policy_result=policy_result,
            bundle=bundle,
            run_ts=run_ts,
            product_id="minimal_slice",
            channel="email",
            resolved_collection=index_meta["collection"],
            operation_context=operation_context,
            export_context=pre_export_audit_context,
        )
        _write_audit_to_postgres(
            run_row=run_row,
            selected_rows=selected_rows,
            rejection_rows=rejection_rows,
            decision_rows=decision_rows,
        )
        export_context = {
            "run_id": bundle.run_id,
            "campaign_id": bundle.campaign_id,
            "policy_version": bundle.policy_version,
            "fs_version": bundle.fs_version,
            "emb_version": bundle.emb_version,
            "model_version": bundle.model_version,
            "index_alias": bundle.index_alias,
            "index_generation": index_meta["collection"],
            "integration_profile_id": run_config.integration_profile_id,
            "source_id": run_config.source_id,
            "export_id": run_config.export_id,
            "channel": "email",
            "exported_ts": run_ts,
        }
        export_result = integrations.export_for_profile(
            profile_id=run_config.integration_profile_id,
            policy_result=export_ready,
            run_id=bundle.run_id,
            output_path=EXPORT_PATH,
            export_context=export_context,
        )
        delivery_result = delivery_runner.execute_delivery_for_run(
            run_id=bundle.run_id,
            delivery_target_id=run_config.delivery_target_id,
            trigger_source="system:run_flow",
            requested_by_role="system_internal",
            requested_by_id="system:run_flow",
        )

        summary = {
            "run_ts": run_ts,
            "status": "ok",
            "operations": operation_context,
            "versions": run_row["version_bundle"],
            "inputs": {
                "raw_path": str(RAW_PATH),
                "feature_mart_path": str(feature_mart_path),
                "embeddings_path": str(embeddings_path),
                "blacklist_path": str(BLACKLIST_PATH),
                "comm_history_path": str(COMM_HISTORY_PATH),
            },
            "quality": {
                "status": "passed",
                "checks": quality_checks,
            },
            "index": index_meta,
            "retrieval": {
                "query_customer_id": query_customer,
                "retrieved_count": len(retrieved),
            },
            "policy": policy_result["summary"],
            "export_path": export_result["export_path"],
            "export_minio_uri": export_result["export_uri"],
            "export": export_result,
            "delivery": delivery_result,
            "audit": {
                "postgres": {
                    "run_table": "audience_run",
                    "selected_rows_written": len(selected_rows),
                    "rejection_summary_rows_written": len(rejection_rows),
                    "policy_decision_rows_written": len(decision_rows),
                }
            },
        }

        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SUMMARY_PATH.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        _append_run_event(
            summary=summary,
            operation_context=operation_context,
            trigger_source="system:run_flow",
        )
        return summary
    except DataQualityError as exc:
        if bundle is None:
            _append_early_failure_run_event(
                early_context=early_context,
                operation_context=operation_context,
                failure_stage=failure_stage,
                error=exc,
            )
            raise
        run_ts = datetime.now(timezone.utc).isoformat()
        logger.error("Data quality gate failed: %s", exc)
        failure_summary = _write_failure_summary(
            bundle=bundle,
            run_ts=run_ts,
            quality_checks=quality_checks,
            error=exc,
            operation_context=operation_context,
        )
        _append_run_event(
            summary=failure_summary,
            operation_context=operation_context,
            trigger_source="system:run_flow",
        )
        raise
    except Exception as exc:
        if bundle is None:
            _append_early_failure_run_event(
                early_context=early_context,
                operation_context=operation_context,
                failure_stage=failure_stage,
                error=exc,
            )
            raise
        run_ts = datetime.now(timezone.utc).isoformat()
        logger.error("Run failed: %s", exc)
        failure_summary = {
            "run_ts": run_ts,
            "status": "failed",
            "operations": operation_context,
            "versions": {
                "fs_version": bundle.fs_version,
                "emb_version": bundle.emb_version,
                "model_version": bundle.model_version,
                "policy_version": bundle.policy_version,
                "index_alias": bundle.index_alias,
                "concrete_qdrant_collection": bundle.concrete_qdrant_collection,
                "run_id": bundle.run_id,
                "campaign_id": bundle.campaign_id,
            },
            "quality": {
                "status": "failed",
                "checks": quality_checks,
                "error": {
                    "code": "RUN_FAILED_INTERNAL",
                    "detail": str(exc),
                },
            },
        }
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SUMMARY_PATH.open("w", encoding="utf-8") as f:
            json.dump(failure_summary, f, indent=2)
        _append_run_event(
            summary=failure_summary,
            operation_context=operation_context,
            trigger_source="system:run_flow",
        )
        raise


if __name__ == "__main__":
    result = run_minimal_vertical_slice()
    print(json.dumps(result, indent=2))
