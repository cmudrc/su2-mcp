"""FastMCP integration coverage for SU2 tool registration and execution flow."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from su2_mcp.fastmcp_server import build_server


def _as_payload(result: object) -> dict[str, object]:
    """Extract a dictionary payload from FastMCP call_tool/list output."""
    if isinstance(result, dict):
        return result

    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, dict):
                return item
            if isinstance(item, Sequence):
                for block in item:
                    text = getattr(block, "text", None)
                    if isinstance(text, str):
                        try:
                            loaded = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(loaded, dict):
                            return loaded

    if isinstance(result, Sequence):
        for block in result:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                try:
                    loaded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(loaded, dict):
                    return loaded

    raise AssertionError(f"Unexpected FastMCP payload shape: {type(result)!r}")


def test_fastmcp_server_supports_tool_discovery() -> None:
    """The FastMCP surface exposes expected SU2 tool names."""
    app = build_server()
    tools = asyncio.run(app.list_tools())
    tool_names = {tool.name for tool in tools}

    expected = {
        "ping",
        "create_su2_session",
        "close_su2_session",
        "get_session_info",
        "get_config_text",
        "parse_config",
        "update_config_entries",
        "set_mesh",
        "generate_mesh_from_step",
        "run_su2_solver",
        "generate_deformed_mesh",
        "get_su2_status",
        "list_result_files",
        "get_result_file_base64",
        "read_history_csv",
        "sample_surface_solution",
    }
    assert expected.issubset(tool_names)


def test_fastmcp_call_flow_for_session_lifecycle() -> None:
    """FastMCP call flow can create, inspect, and close SU2 sessions."""
    app = build_server()

    created = _as_payload(asyncio.run(app.call_tool("create_su2_session", {})))
    session_id = str(created["session_id"])

    info = _as_payload(
        asyncio.run(app.call_tool("get_session_info", {"session_id": session_id}))
    )
    closed = _as_payload(
        asyncio.run(
            app.call_tool(
                "close_su2_session",
                {"session_id": session_id, "delete_workdir": True},
            )
        )
    )

    assert info["session_id"] == session_id
    assert closed["success"] is True


def test_fastmcp_invalid_session_surfaces_structured_error() -> None:
    """Missing sessions return a stable not_found payload through FastMCP."""
    app = build_server()

    payload = _as_payload(
        asyncio.run(app.call_tool("get_session_info", {"session_id": "invalid"}))
    )

    assert payload["error"]["type"] == "not_found"
    assert "Unknown session_id" in payload["error"]["message"]
