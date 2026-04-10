import json
from typing import Any, List, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from pipelines.minimal_slice import (
    control_plane,
    delivery_runner,
    integrations,
    lifecycle_service,
    run_flow,
)
from pipelines.minimal_slice.config import SUMMARY_PATH
from pipelines.minimal_slice.data_quality import DataQualityError
from pipelines.minimal_slice.lifecycle_service import LifecycleActor
from pipelines.minimal_slice.policy_decision_audit import fetch_policy_decision_audit
from pipelines.minimal_slice.retrieval import retrieve_similar
from pipelines.version_bundle import VersionBundle
from services.retrieval_api.auth import (
    Principal,
    require_admin,
    require_campaign_or_admin,
)
from services.retrieval_api.operator_ui import OPERATOR_STATIC_DIR, OPERATOR_UI_ROUTER

app = FastAPI(title="Audience Engine Retrieval API", version="0.1.0")
app.mount(
    "/operator/static",
    StaticFiles(directory=OPERATOR_STATIC_DIR),
    name="operator_static",
)
app.include_router(OPERATOR_UI_ROUTER)


@app.get("/metrics", include_in_schema=False)
@app.get("/metrics/", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


class RetrieveRequest(BaseModel):
    top_k: int = Field(default=20, ge=1, le=200)
    query_text: Optional[str] = None
    query_customer_id: Optional[str] = None
    product_line: Optional[str] = None
    region_codes: Optional[List[str]] = None
    segment_ids: Optional[List[str]] = None
    include_employee: bool = False
    include_do_not_contact: bool = False
    include_opt_out: bool = False
    include_legal_suppression: bool = False
    min_tenure_months: Optional[int] = Field(default=None, ge=0)
    max_delinquency_12m_count: Optional[int] = Field(default=None, ge=0)
    fs_version: Optional[str] = None
    emb_version: Optional[str] = None
    policy_version: Optional[str] = None


class OperatorDefaultsUpdateRequest(BaseModel):
    default_policy_version: Optional[str] = None
    default_integration_profile_id: Optional[str] = None
    default_delivery_target_id: Optional[str] = None


class TriggerRunRequest(BaseModel):
    campaign_id: Optional[str] = None
    policy_version: Optional[str] = None
    integration_profile_id: Optional[str] = None
    delivery_target_id: Optional[str] = None
    requested_size: int = Field(default=20, ge=1, le=500)


class TriggerDeliveryRequest(BaseModel):
    run_id: str
    delivery_target_id: Optional[str] = None


@app.get("/healthz")
def healthz() -> dict:
    bundle = _load_latest_version_bundle()
    return {"status": "ok", "version_bundle": bundle.__dict__ if bundle else None}


def _load_latest_version_bundle() -> Optional[VersionBundle]:
    if not SUMMARY_PATH.exists():
        return None
    with SUMMARY_PATH.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    versions = summary.get("versions")
    if not isinstance(versions, dict):
        return None
    try:
        return VersionBundle(**versions)
    except TypeError:
        return None


def _load_latest_summary() -> Optional[dict[str, Any]]:
    if not SUMMARY_PATH.exists():
        return None
    with SUMMARY_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return None
    return payload


@app.post("/v1/retrieve")
def retrieve(
    request: RetrieveRequest,
    principal: Principal = Depends(require_campaign_or_admin),
) -> dict:
    _ = principal
    if not request.query_text and not request.query_customer_id:
        raise HTTPException(
            status_code=400, detail="Provide query_text or query_customer_id"
        )

    try:
        rows = retrieve_similar(
            top_k=request.top_k,
            query_text=request.query_text,
            query_customer_id=request.query_customer_id,
            product_line=request.product_line,
            region_codes=request.region_codes,
            segment_ids=request.segment_ids,
            include_employee=request.include_employee,
            include_do_not_contact=request.include_do_not_contact,
            include_opt_out=request.include_opt_out,
            include_legal_suppression=request.include_legal_suppression,
            min_tenure_months=request.min_tenure_months,
            max_delinquency_12m_count=request.max_delinquency_12m_count,
            fs_version=request.fs_version,
            emb_version=request.emb_version,
            policy_version=request.policy_version,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"count": len(rows), "results": rows}


@app.get("/v1/policy/decisions/{run_id}/{customer_id}")
def get_policy_decision(
    run_id: str,
    customer_id: str,
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    try:
        UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid run_id format (expected UUID): {run_id}",
        ) from exc
    try:
        decision = fetch_policy_decision_audit(run_id=run_id, customer_id=customer_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if decision is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Policy decision not found for run_id={run_id} "
                f"customer_id={customer_id}"
            ),
        )
    return decision


def _lifecycle_actor(principal: Principal) -> LifecycleActor:
    return LifecycleActor(role=principal.role.value, actor_id=principal.actor_id)


@app.get("/v1/admin/control-plane/model")
def get_operational_control_model(
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    return control_plane.describe_operational_model()


@app.get("/v1/admin/control-plane/defaults")
def get_operator_defaults(
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    defaults = control_plane.load_operator_defaults()
    return {
        "default_policy_version": defaults.default_policy_version,
        "default_integration_profile_id": defaults.default_integration_profile_id,
        "default_delivery_target_id": defaults.default_delivery_target_id,
    }


@app.put("/v1/admin/control-plane/defaults")
def update_operator_defaults(
    request: OperatorDefaultsUpdateRequest,
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    if (
        request.default_policy_version is None
        and request.default_integration_profile_id is None
        and request.default_delivery_target_id is None
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide default_policy_version and/or "
                "default_integration_profile_id and/or "
                "default_delivery_target_id."
            ),
        )
    try:
        defaults = control_plane.save_operator_defaults(
            default_policy_version=request.default_policy_version,
            default_integration_profile_id=request.default_integration_profile_id,
            default_delivery_target_id=request.default_delivery_target_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "default_policy_version": defaults.default_policy_version,
        "default_integration_profile_id": defaults.default_integration_profile_id,
        "default_delivery_target_id": defaults.default_delivery_target_id,
    }


@app.get("/v1/admin/control-plane/integrations")
def list_integrations(
    include_planned: bool = Query(default=True),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    sources = control_plane.list_source_connectors(include_planned=include_planned)
    exports = control_plane.list_export_targets(include_planned=include_planned)
    profiles = control_plane.list_integration_profiles(include_planned=include_planned)
    return integrations.annotate_runtime_readiness(
        sources=sources,
        exports=exports,
        profiles=profiles,
    )


@app.get("/v1/admin/control-plane/policies")
def list_control_plane_policies(
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    defaults = control_plane.load_operator_defaults()
    policies = control_plane.list_policies()
    return {
        "default_policy_version": defaults.default_policy_version,
        "policies": policies,
    }


@app.get("/v1/admin/control-plane/delivery-targets")
def list_control_plane_delivery_targets(
    include_planned: bool = Query(default=True),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    targets = delivery_runner.list_delivery_targets(include_planned=include_planned)
    defaults = control_plane.load_operator_defaults()
    return {
        "default_delivery_target_id": defaults.default_delivery_target_id,
        "targets": targets,
    }


@app.get("/v1/admin/runs/latest-summary")
def get_latest_run_summary(
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    summary = _load_latest_summary()
    if summary is None:
        raise HTTPException(status_code=404, detail="No run summary available yet.")
    return summary


@app.get("/v1/admin/runs/recent")
def list_recent_runs(
    limit: int = Query(default=20, ge=1, le=200),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    try:
        rows = control_plane.list_recent_run_events(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": len(rows), "runs": rows}


@app.post("/v1/admin/runs/trigger")
def trigger_operator_run(
    request: TriggerRunRequest,
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    try:
        summary = run_flow.run_minimal_vertical_slice(
            campaign_id=request.campaign_id,
            policy_version=request.policy_version,
            integration_profile_id=request.integration_profile_id,
            delivery_target_id=request.delivery_target_id,
            requested_size=request.requested_size,
        )
    except DataQualityError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    versions = summary.get("versions", {})
    return {
        "status": summary.get("status"),
        "run_id": versions.get("run_id"),
        "campaign_id": versions.get("campaign_id"),
        "policy_version": versions.get("policy_version"),
        "integration_profile_id": summary.get("operations", {}).get(
            "integration_profile_id"
        ),
        "delivery_target_id": summary.get("operations", {}).get("delivery_target_id"),
        "summary": summary,
    }


@app.post("/v1/admin/delivery/trigger")
def trigger_delivery_for_run(
    request: TriggerDeliveryRequest,
    principal: Principal = Depends(require_admin),
) -> dict:
    try:
        UUID(request.run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid run_id format (expected UUID): {request.run_id}",
        ) from exc

    target_id = request.delivery_target_id
    if not target_id:
        target_id = control_plane.load_operator_defaults().default_delivery_target_id

    try:
        result = delivery_runner.execute_delivery_for_run(
            run_id=request.run_id,
            delivery_target_id=target_id,
            trigger_source="api:/v1/admin/delivery/trigger",
            requested_by_role=principal.role.value,
            requested_by_id=principal.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result


@app.get("/v1/admin/delivery/jobs/recent")
def list_recent_delivery_jobs(
    limit: int = Query(default=20, ge=1, le=200),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    try:
        rows = delivery_runner.list_recent_delivery_jobs(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": len(rows), "jobs": rows}


@app.get("/v1/admin/delivery/attempts/recent")
def list_recent_delivery_attempts(
    limit: int = Query(default=50, ge=1, le=500),
    run_id: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    if run_id is not None:
        try:
            UUID(run_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid run_id format (expected UUID): {run_id}",
            ) from exc
    try:
        rows = delivery_runner.list_recent_delivery_attempts(limit=limit, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": len(rows), "attempts": rows}


@app.get("/v1/admin/delivery/runs/{run_id}/latest-summary")
def get_latest_delivery_summary_for_run(
    run_id: str,
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    try:
        UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid run_id format (expected UUID): {run_id}",
        ) from exc
    try:
        summary = delivery_runner.latest_delivery_summary_for_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"No delivery summary found for run_id={run_id}",
        )
    return summary


@app.get("/v1/admin/delivery/runs/{run_id}/records")
def list_delivery_records_for_run(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    try:
        UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid run_id format (expected UUID): {run_id}",
        ) from exc
    try:
        rows = delivery_runner.list_delivery_records_for_run(run_id=run_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": len(rows), "records": rows}


@app.get("/v1/admin/index/generations/latest")
def get_latest_index_generation(
    status: Optional[str] = Query(default=None),
    alias_name: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    generation = lifecycle_service.get_generation_status(
        status=status, alias_name=alias_name
    )
    if generation is None:
        raise HTTPException(
            status_code=404,
            detail="No index generation found for the requested filter.",
        )
    return generation


@app.get("/v1/admin/index/generations")
def list_index_generations(
    limit: int = Query(default=20, ge=1, le=200),
    status: Optional[str] = Query(default=None),
    alias_name: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    rows = lifecycle_service.list_generations(
        limit=limit,
        status=status,
        alias_name=alias_name,
    )
    return {"count": len(rows), "generations": rows}


@app.post("/v1/admin/index/generations/validate-latest")
def validate_latest_index_generation(
    principal: Principal = Depends(require_admin),
) -> dict:
    try:
        return lifecycle_service.validate_latest(actor=_lifecycle_actor(principal))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/admin/index/alias/promote-latest")
def promote_latest_index_alias(
    principal: Principal = Depends(require_admin),
) -> dict:
    try:
        return lifecycle_service.promote_latest(actor=_lifecycle_actor(principal))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/admin/index/alias/rollback-latest")
def rollback_latest_index_alias(
    principal: Principal = Depends(require_admin),
) -> dict:
    try:
        return lifecycle_service.rollback_latest(actor=_lifecycle_actor(principal))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/v1/admin/index/lifecycle-audit")
def list_index_lifecycle_audit(
    limit: int = Query(default=20, ge=1, le=200),
    alias_name: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_admin),
) -> dict:
    _ = principal
    rows = lifecycle_service.list_lifecycle_audit(limit=limit, alias_name=alias_name)
    return {"count": len(rows), "actions": rows}
