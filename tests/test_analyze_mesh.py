"""Coverage for the analyze_mesh tool."""

from __future__ import annotations

from su2_mcp.tools import mesh_tools, session


def test_analyze_mesh_missing_session() -> None:
    """Unknown session IDs return not_found."""
    result = mesh_tools.analyze_mesh("missing")
    assert result["error"]["type"] == "not_found"


def test_analyze_mesh_no_mesh_file() -> None:
    """Sessions without a mesh file return not_found."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    result = mesh_tools.analyze_mesh(session_id)
    assert result["error"]["type"] == "not_found"

    session.close_su2_session(session_id, delete_workdir=True)
