"""Retrieval API package."""

# Import for side effects so operator control-plane routes register on package load.
from . import operator_control_plane_ui  # noqa: F401
from . import operator_user_admin_ui  # noqa: F401
