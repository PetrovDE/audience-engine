from __future__ import annotations

import pytest

from pipelines.minimal_slice import control_plane_registry


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    [
        ("draft", "validated"),
        ("validated", "draft"),
        ("validated", "active"),
        ("active", "deprecated"),
        ("deprecated", "active"),
        ("deprecated", "retired"),
    ],
)
def test_validate_lifecycle_transition_allows_documented_edges(
    current_state: str, target_state: str
):
    control_plane_registry.validate_lifecycle_transition(current_state, target_state)


@pytest.mark.parametrize(
    ("current_state", "target_state"),
    [
        ("draft", "active"),
        ("draft", "retired"),
        ("active", "retired"),
        ("retired", "active"),
    ],
)
def test_validate_lifecycle_transition_rejects_forbidden_edges(
    current_state: str, target_state: str
):
    with pytest.raises(ValueError, match="Invalid lifecycle transition"):
        control_plane_registry.validate_lifecycle_transition(
            current_state,
            target_state,
        )
