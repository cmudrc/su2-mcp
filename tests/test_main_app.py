"""Tests for FastMCP application wiring."""

from __future__ import annotations

import asyncio

from su2_mcp_server import fastmcp_server
from su2_mcp_server.tools import PingRequest, ping


def test_create_app_registers_all_tools() -> None:
    """FastMCP app exposes all SU2 tools with clear instructions."""
    app = fastmcp_server.build_server()

    tools = asyncio.run(app.list_tools())
    tool_names = {tool.name for tool in tools}

    expected_tools = {
        "ping",
        "create_su2_session",
        "close_su2_session",
        "get_session_info",
        "get_config_text",
        "parse_config",
        "update_config_entries",
        "set_mesh",
        "run_su2_solver",
        "generate_deformed_mesh",
        "list_result_files",
        "get_result_file_base64",
        "read_history_csv",
        "sample_surface_solution",
    }

    assert expected_tools.issubset(tool_names)
    assert app.name == fastmcp_server.APP_NAME
    assert app.instructions is not None
    assert fastmcp_server.APP_INSTRUCTIONS in app.instructions


def test_ping_tool_returns_health_payload() -> None:
    """Ping should answer without accessing SU2 binaries."""
    response = ping(PingRequest(message="hello"))

    assert response.ok is True
    assert response.message == "hello"
    assert response.server == "su2-mcp"
    assert response.timestamp
