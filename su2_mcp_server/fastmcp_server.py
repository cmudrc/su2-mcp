"""FastMCP server factory for SU2 tooling."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from mcp.server.fastmcp import FastMCP

from su2_mcp_server import tools

APP_NAME = "su2-mcp"
APP_INSTRUCTIONS = (
    "Expose SU2 session lifecycle, configuration, solver, and results management tools "
    "using FastMCP. Create a session first, then operate on its config, runs, and outputs."
)


def _server_version() -> str:
    """Return the package version, falling back to a development marker."""
    try:
        return version("su2-mcp-server")
    except PackageNotFoundError:
        return "0.0.0-dev"


def build_server() -> FastMCP:
    """Construct a FastMCP server with all SU2 tools registered."""
    server = FastMCP(
        APP_NAME,
        instructions=f"{APP_INSTRUCTIONS} Version: {_server_version()}.",
    )
    server.add_tool(tools.ping)
    server.add_tool(tools.create_su2_session)
    server.add_tool(tools.close_su2_session)
    server.add_tool(tools.get_session_info)
    server.add_tool(tools.get_config_text)
    server.add_tool(tools.parse_config)
    server.add_tool(tools.update_config_entries)
    server.add_tool(tools.set_mesh)
    server.add_tool(tools.run_su2_solver)
    server.add_tool(tools.generate_deformed_mesh)
    server.add_tool(tools.get_su2_status)
    server.add_tool(tools.list_result_files)
    server.add_tool(tools.get_result_file_base64)
    server.add_tool(tools.read_history_csv)
    server.add_tool(tools.sample_surface_solution)
    return server


__all__ = ["APP_INSTRUCTIONS", "APP_NAME", "build_server"]
