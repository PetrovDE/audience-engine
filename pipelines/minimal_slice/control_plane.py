from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import delivery_registry
from .config import POLICY_VERSION

ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_DIR = ROOT / "governance"
INTEGRATION_REGISTRY_PATH = (
    GOVERNANCE_DIR / "integrations" / "integration_registry.yaml"
)
POLICY_REGISTRY_PATH = GOVERNANCE_DIR / "policies" / "policy_registry.yaml"

CONTROL_PLANE_DIR = ROOT / "data" / "minimal_slice" / "control_plane"
OPERATOR_STATE_PATH = CONTROL_PLANE_DIR / "operator_state.json"
RUN_EVENTS_PATH = CONTROL_PLANE_DIR / "run_events.jsonl"

OPERATOR_MAIN_DAG_ID = "audience_engine_operator_main"
LEGACY_INTERNAL_DAG_ID = "audience_engine_minimal_slice_e2e"


@dataclass(frozen=True)
class OperatorDefaults:
    default_policy_version: str
    default_integration_profile_id: str
    default_delivery_target_id: str


@dataclass(frozen=True)
class OperationalRunConfig:
    policy_version: str
    policy_selection_source: str
    integration_profile_id: str
    integration_selection_source: str
    delivery_target_id: str
    delivery_selection_source: str
    source_id: str
    export_id: str


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Required control-plane artifact missing: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML object in {path}")
    return payload


def _integration_registry() -> dict[str, Any]:
    return _load_yaml(INTEGRATION_REGISTRY_PATH)


def _policy_registry() -> dict[str, Any]:
    return _load_yaml(POLICY_REGISTRY_PATH)


def list_source_connectors(*, include_planned: bool = True) -> list[dict[str, Any]]:
    sources = _integration_registry().get("sources", [])
    rows = [dict(row) for row in sources if isinstance(row, dict)]
    if include_planned:
        return rows
    return [r for r in rows if r.get("implementation_status") == "implemented"]


def list_export_targets(*, include_planned: bool = True) -> list[dict[str, Any]]:
    exports = _integration_registry().get("exports", [])
    rows = [dict(row) for row in exports if isinstance(row, dict)]
    if include_planned:
        return rows
    return [r for r in rows if r.get("implementation_status") == "implemented"]


def list_integration_profiles(*, include_planned: bool = True) -> list[dict[str, Any]]:
    profiles = _integration_registry().get("profiles", [])
    rows = [dict(row) for row in profiles if isinstance(row, dict)]
    if include_planned:
        return rows
    return [r for r in rows if r.get("implementation_status") == "implemented"]


def list_delivery_targets(*, include_planned: bool = True) -> list[dict[str, Any]]:
    return delivery_registry.list_delivery_targets(include_planned=include_planned)


def _connector_by_id(kind: str, connector_id: str) -> dict[str, Any]:
    rows = list_source_connectors() if kind == "source" else list_export_targets()
    for row in rows:
        row_id = row.get("source_id") if kind == "source" else row.get("export_id")
        if row_id == connector_id:
            return row
    raise ValueError(f"Unknown {kind} connector: {connector_id}")


def get_integration_profile(profile_id: str) -> dict[str, Any]:
    for profile in list_integration_profiles():
        if profile.get("profile_id") == profile_id:
            return profile
    raise ValueError(f"Unknown integration profile: {profile_id}")


def _ensure_selectable_integration_profile(
    profile_id: str, *, require_implemented: bool, selection_kind: str
) -> dict[str, Any]:
    profile = get_integration_profile(profile_id)
    status = str(profile.get("implementation_status", "unknown"))
    if require_implemented and status != "implemented":
        raise ValueError(
            f"{selection_kind} integration profile is not implemented: "
            f"{profile_id} (status={status})"
        )
    return profile


def _active_policy_versions() -> list[str]:
    active: list[str] = []
    for policy in _policy_registry().get("policies", []):
        if not isinstance(policy, dict):
            continue
        if policy.get("status") != "active":
            continue
        policy_version = policy.get("policy_version")
        if policy_version:
            active.append(str(policy_version))
    return active


def list_policies() -> list[dict[str, Any]]:
    active = set(_active_policy_versions())
    policies = []
    for policy in _policy_registry().get("policies", []):
        if not isinstance(policy, dict):
            continue
        policy_version = str(policy.get("policy_version", "")).strip()
        if not policy_version:
            continue
        policies.append(
            {
                "policy_version": policy_version,
                "status": str(policy.get("status", "unknown")),
                "scope": str(policy.get("scope", "")),
                "description": str(policy.get("description", "")),
                "is_active": policy_version in active,
            }
        )
    return policies


def _ensure_known_policy(policy_version: str) -> None:
    known = {row["policy_version"] for row in list_policies()}
    if policy_version not in known:
        raise ValueError(f"Unknown policy_version: {policy_version}")


def _default_policy_version() -> str:
    active = _active_policy_versions()
    if active:
        return active[0]
    return POLICY_VERSION


def _default_profile_and_delivery_target() -> tuple[str, str]:
    profiles = [
        row
        for row in list_integration_profiles(include_planned=False)
        if str(row.get("profile_id", "")).strip()
    ]
    targets = [
        row
        for row in list_delivery_targets(include_planned=False)
        if str(row.get("delivery_target_id", "")).strip()
    ]
    for profile in profiles:
        profile_id = str(profile["profile_id"])
        export_id = str(profile.get("export_id", "")).strip()
        if not export_id:
            continue
        try:
            export_target = _connector_by_id("export", export_id)
        except ValueError:
            continue
        for target in targets:
            delivery_target_id = str(target["delivery_target_id"])
            try:
                delivery_registry.ensure_delivery_target_compatible_with_export(
                    delivery_target_id,
                    export_target=export_target,
                    selection_kind="Default",
                )
            except ValueError:
                continue
            return profile_id, delivery_target_id
    raise ValueError(
        "No compatible implemented integration profile and delivery target pair found"
    )


def _fallback_defaults() -> OperatorDefaults:
    profile_id, delivery_target_id = _default_profile_and_delivery_target()
    return OperatorDefaults(
        default_policy_version=_default_policy_version(),
        default_integration_profile_id=profile_id,
        default_delivery_target_id=delivery_target_id,
    )


def _read_operator_state() -> dict[str, Any]:
    if not OPERATOR_STATE_PATH.exists():
        return {}
    with OPERATOR_STATE_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def load_operator_defaults() -> OperatorDefaults:
    fallback = _fallback_defaults()
    state = _read_operator_state()
    candidate_policy = str(
        state.get("default_policy_version", fallback.default_policy_version)
    )
    candidate_profile = str(
        state.get(
            "default_integration_profile_id", fallback.default_integration_profile_id
        )
    )
    candidate_delivery = str(
        state.get("default_delivery_target_id", fallback.default_delivery_target_id)
    )

    try:
        _ensure_known_policy(candidate_policy)
    except ValueError:
        candidate_policy = fallback.default_policy_version

    try:
        _ensure_selectable_integration_profile(
            candidate_profile,
            require_implemented=True,
            selection_kind="Default",
        )
    except ValueError:
        candidate_profile = fallback.default_integration_profile_id

    try:
        delivery_registry.ensure_selectable_delivery_target(
            candidate_delivery,
            selection_kind="Default",
        )
    except ValueError:
        candidate_delivery = fallback.default_delivery_target_id

    profile = _ensure_selectable_integration_profile(
        candidate_profile,
        require_implemented=True,
        selection_kind="Default",
    )
    export_target = _connector_by_id("export", str(profile.get("export_id", "")).strip())
    try:
        delivery_registry.ensure_delivery_target_compatible_with_export(
            candidate_delivery,
            export_target=export_target,
            selection_kind="Default",
        )
    except ValueError:
        candidate_profile = fallback.default_integration_profile_id
        candidate_delivery = fallback.default_delivery_target_id

    return OperatorDefaults(
        default_policy_version=candidate_policy,
        default_integration_profile_id=candidate_profile,
        default_delivery_target_id=candidate_delivery,
    )


def save_operator_defaults(
    *,
    default_policy_version: str | None = None,
    default_integration_profile_id: str | None = None,
    default_delivery_target_id: str | None = None,
) -> OperatorDefaults:
    current = load_operator_defaults()
    resolved_policy = (
        default_policy_version.strip()
        if isinstance(default_policy_version, str)
        else current.default_policy_version
    )
    resolved_profile = (
        default_integration_profile_id.strip()
        if isinstance(default_integration_profile_id, str)
        else current.default_integration_profile_id
    )
    resolved_delivery_target = (
        default_delivery_target_id.strip()
        if isinstance(default_delivery_target_id, str)
        else current.default_delivery_target_id
    )

    _ensure_known_policy(resolved_policy)
    profile = _ensure_selectable_integration_profile(
        resolved_profile,
        require_implemented=True,
        selection_kind="Default",
    )
    delivery_registry.ensure_selectable_delivery_target(
        resolved_delivery_target,
        selection_kind="Default",
    )
    export_target = _connector_by_id("export", str(profile.get("export_id", "")).strip())
    delivery_registry.ensure_delivery_target_compatible_with_export(
        resolved_delivery_target,
        export_target=export_target,
        selection_kind="Default",
    )

    payload = {
        "default_policy_version": resolved_policy,
        "default_integration_profile_id": resolved_profile,
        "default_delivery_target_id": resolved_delivery_target,
    }
    OPERATOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OPERATOR_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return OperatorDefaults(
        default_policy_version=resolved_policy,
        default_integration_profile_id=resolved_profile,
        default_delivery_target_id=resolved_delivery_target,
    )


def resolve_run_configuration(
    *,
    policy_version: str | None,
    integration_profile_id: str | None,
    delivery_target_id: str | None = None,
) -> OperationalRunConfig:
    defaults = load_operator_defaults()

    resolved_policy = (
        policy_version.strip() if policy_version else defaults.default_policy_version
    )
    policy_selection_source = "request" if policy_version else "operator_default"
    _ensure_known_policy(resolved_policy)

    resolved_profile_id = (
        integration_profile_id.strip()
        if integration_profile_id
        else defaults.default_integration_profile_id
    )
    integration_selection_source = (
        "request" if integration_profile_id else "operator_default"
    )
    resolved_delivery_target_id = (
        delivery_target_id.strip()
        if delivery_target_id
        else defaults.default_delivery_target_id
    )
    delivery_selection_source = "request" if delivery_target_id else "operator_default"
    delivery_registry.ensure_selectable_delivery_target(
        resolved_delivery_target_id,
        selection_kind="Selected",
    )

    profile = _ensure_selectable_integration_profile(
        resolved_profile_id,
        require_implemented=True,
        selection_kind="Selected",
    )

    source_id = str(profile.get("source_id", "")).strip()
    export_id = str(profile.get("export_id", "")).strip()
    if not source_id or not export_id:
        raise ValueError(
            "Integration profile is missing source/export connector ids: "
            f"{resolved_profile_id}"
        )

    source = _connector_by_id("source", source_id)
    export = _connector_by_id("export", export_id)
    if source.get("implementation_status") != "implemented":
        raise ValueError(f"Source connector is not implemented: {source_id}")
    if export.get("implementation_status") != "implemented":
        raise ValueError(f"Export target is not implemented: {export_id}")
    delivery_registry.ensure_delivery_target_compatible_with_export(
        resolved_delivery_target_id,
        export_target=export,
        selection_kind="Selected",
    )

    return OperationalRunConfig(
        policy_version=resolved_policy,
        policy_selection_source=policy_selection_source,
        integration_profile_id=resolved_profile_id,
        integration_selection_source=integration_selection_source,
        delivery_target_id=resolved_delivery_target_id,
        delivery_selection_source=delivery_selection_source,
        source_id=source_id,
        export_id=export_id,
    )


def describe_operational_model() -> dict[str, Any]:
    return {
        "primary_operator_pipeline_entrypoint": {
            "airflow_dag_id": OPERATOR_MAIN_DAG_ID,
            "api_trigger_endpoint": "/v1/admin/runs/trigger",
            "expected_trigger_params": [
                "campaign_id",
                "policy_version",
                "integration_profile_id",
                "delivery_target_id",
                "requested_size",
            ],
        },
        "orchestration_model": {
            "summary": (
                "API trigger and Airflow DAG are separate orchestrators over the "
                "same runtime modules and governance contracts."
            ),
            "api_orchestrator": (
                "services.retrieval_api.app -> "
                "pipelines.minimal_slice.run_flow.run_minimal_vertical_slice"
            ),
            "airflow_orchestrator": (
                "pipelines.airflow_dags.audience_engine_dags task chain"
            ),
            "shared_runtime_modules": [
                "pipelines.minimal_slice.control_plane",
                "pipelines.minimal_slice.integrations",
                "pipelines.minimal_slice.lifecycle_service",
                "pipelines.minimal_slice.policy_engine",
            ],
        },
        "defaults_validation": {
            "default_policy_version": "must exist in policy registry",
            "default_integration_profile_id": (
                "must reference an implemented integration profile"
            ),
            "default_delivery_target_id": (
                "must reference an implemented delivery target"
            ),
            "default_profile_delivery_compatibility": (
                "selected delivery target must be compatible with selected "
                "integration export target"
            ),
        },
        "operator_facing_dags": [OPERATOR_MAIN_DAG_ID],
        "internal_dags": [LEGACY_INTERNAL_DAG_ID],
        "operator_facing_api_surfaces": [
            "/v1/retrieve",
            "/v1/admin/control-plane/model",
            "/v1/admin/control-plane/defaults",
            "/v1/admin/control-plane/integrations",
            "/v1/admin/control-plane/delivery-targets",
            "/v1/admin/control-plane/policies",
            "/v1/admin/runs/trigger",
            "/v1/admin/runs/recent",
            "/v1/admin/runs/latest-summary",
            "/v1/admin/delivery/trigger",
            "/v1/admin/delivery/jobs/recent",
            "/v1/admin/delivery/attempts/recent",
            "/v1/admin/delivery/runs/{run_id}/latest-summary",
            "/v1/admin/delivery/runs/{run_id}/records",
            "/v1/admin/index/*",
            "/v1/policy/decisions/{run_id}/{customer_id}",
        ],
        "system_internal_surfaces": [
            "pipelines.minimal_slice.run_flow.run_minimal_vertical_slice",
            "pipelines.minimal_slice.lifecycle_service",
            "pipelines.minimal_slice.qdrant_index",
        ],
    }


def append_run_event(event: dict[str, Any]) -> None:
    RUN_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RUN_EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def list_recent_run_events(*, limit: int = 20) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if not RUN_EVENTS_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with RUN_EVENTS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    rows.reverse()
    return rows[:limit]
