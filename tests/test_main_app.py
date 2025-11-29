"""Tests for FastMCP application wiring."""

from __future__ import annotations

import asyncio

from su2_mcp_server import main


def test_create_app_registers_all_tools() -> None:
    """FastMCP app exposes all SU2 tools with clear instructions."""
    app = main.create_app()

    tools = asyncio.run(app.list_tools())
    tool_names = {tool.name for tool in tools}

    expected_tools = {
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
    assert app.name == main.APP_NAME
    assert app.instructions is not None
    assert main.APP_INSTRUCTIONS in app.instructions
