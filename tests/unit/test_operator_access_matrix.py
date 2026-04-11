from __future__ import annotations

from services.retrieval_api.auth import Role
from services.retrieval_api.operator_access import (
    evaluate_access,
    filtered_nav_items,
)


def test_nav_visibility_campaign_user_hides_admin_and_control_plane() -> None:
    nav_items = [
        {"path": "/operator/dashboard", "label": "Dashboard"},
        {"path": "/operator/defaults", "label": "Defaults"},
        {"path": "/operator/trigger-run", "label": "Trigger Run"},
        {"path": "/operator/control-plane/versions", "label": "Control-Plane Versions"},
        {"path": "/operator/admin/users", "label": "User Admin"},
    ]
    filtered = filtered_nav_items(nav_items=nav_items, roles=(Role.CAMPAIGN_USER,))
    paths = {row["path"] for row in filtered}
    assert "/operator/dashboard" in paths
    assert "/operator/trigger-run" in paths
    assert "/operator/defaults" not in paths
    assert "/operator/control-plane/versions" not in paths
    assert "/operator/admin/users" not in paths


def test_page_access_matrix_allows_data_engineer_defaults_read() -> None:
    decision = evaluate_access(
        roles=(Role.DATA_ENGINEER,),
        path="/operator/defaults",
        method="GET",
    )
    assert decision.allowed is True
    assert decision.page_key == "operator.defaults"


def test_page_access_matrix_denies_campaign_user_control_plane() -> None:
    decision = evaluate_access(
        roles=(Role.CAMPAIGN_USER,),
        path="/operator/control-plane/versions",
        method="GET",
    )
    assert decision.allowed is False
    assert decision.page_key == "operator.control_plane_versions"
    assert "Control-plane pages are limited" in (decision.message or "")


def test_action_access_matrix_blocks_ml_lifecycle_but_allows_evidence() -> None:
    lifecycle = evaluate_access(
        roles=(Role.ML_ANALYST,),
        path="/operator/control-plane/versions/feature_sets/fs_credit/v1/actions/activate",
        method="POST",
    )
    assert lifecycle.allowed is False
    assert lifecycle.action_key == "operator.control_plane.lifecycle.transition"
    assert "Lifecycle transition actions are admin_operator-only" in (
        lifecycle.message or ""
    )

    evidence = evaluate_access(
        roles=(Role.ML_ANALYST,),
        path="/operator/control-plane/versions/feature_sets/fs_credit/v1/evidence",
        method="POST",
    )
    assert evidence.allowed is True
    assert evidence.action_key == "operator.control_plane.evidence.record"


def test_action_access_matrix_allows_admin_user_management_actions() -> None:
    decision = evaluate_access(
        roles=(Role.ADMIN_OPERATOR,),
        path="/operator/admin/users/abc/roles/assign",
        method="POST",
    )
    assert decision.allowed is True
    assert decision.action_key == "operator.user_admin.manage"

