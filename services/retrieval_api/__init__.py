"""Retrieval API package."""

# Import for side effects so operator control-plane routes register on package load.
from . import (
    operator_control_plane_ui,  # noqa: F401
    operator_login_ui,  # noqa: F401
    operator_user_admin_ui,  # noqa: F401
    operator_user_credentials_ui,  # noqa: F401
)
