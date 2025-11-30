"""MCP tools for checking SU2 binaries."""

from __future__ import annotations

from su2_mcp_server.su2_availability import check_su2_installation


def get_su2_status() -> dict[str, object]:
    """Return SU2 availability information for the host.

    Returns:
        Mapping that indicates whether any SU2 binaries are available alongside
        per-binary details.

    Examples:
        >>> status = get_su2_status()
        >>> set(status.keys()) == {"installed", "binaries", "missing"}
        True

    """
    return check_su2_installation()


__all__ = ["get_su2_status"]
