"""MCP server entrypoint for SU2 integrations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version

from mcp.server.fastmcp import FastMCP

from su2_mcp_server.tools import config_tools, results_tools, run_tools, session

APP_NAME = "su2-mcp"
APP_INSTRUCTIONS = (
    "Expose SU2 session lifecycle, configuration, solver, and results management tools "
    "using FastMCP. Create a session first, then operate on its config, runs, and outputs."
)


def _server_version() -> str:
    """Return the package version, falling back to a development marker.

    Returns:
        Package version string from installed metadata, or a development marker when
        running from source.

    """
    try:
        return version("su2-mcp-server")
    except PackageNotFoundError:
        return "0.0.0-dev"


def _register_tool(app: FastMCP, name: str, func: Callable[..., Mapping[str, object]]) -> None:
    """Register a tool with the provided FastMCP application.

    Args:
        app: The FastMCP instance to receive the tool registration.
        name: Public name to expose for the tool.
        func: Callable implementing the tool logic.

    """
    app.add_tool(func, name=name)


def _register_tools(app: FastMCP) -> None:
    """Register all SU2 tools on the FastMCP application.

    Args:
        app: The FastMCP application to enrich with SU2 tools.

    """
    # Session tools
    _register_tool(app, "create_su2_session", session.create_su2_session)
    _register_tool(app, "close_su2_session", session.close_su2_session)
    _register_tool(app, "get_session_info", session.get_session_info)

    # Config tools
    _register_tool(app, "get_config_text", config_tools.get_config_text)
    _register_tool(app, "parse_config", config_tools.parse_config)
    _register_tool(app, "update_config_entries", config_tools.update_config_entries)
    _register_tool(app, "set_mesh", config_tools.set_mesh)

    # Run tools
    _register_tool(app, "run_su2_solver", run_tools.run_su2_solver)
    _register_tool(app, "generate_deformed_mesh", run_tools.generate_deformed_mesh)

    # Result tools
    _register_tool(app, "list_result_files", results_tools.list_result_files)
    _register_tool(app, "get_result_file_base64", results_tools.get_result_file_base64)
    _register_tool(app, "read_history_csv", results_tools.read_history_csv)
    _register_tool(app, "sample_surface_solution", results_tools.sample_surface_solution)


def create_app() -> FastMCP:
    """Build a FastMCP application with all SU2 tools registered.

    Returns:
        A configured FastMCP application ready to be served over any supported MCP
        transport.

    Examples:
        >>> from su2_mcp_server import main
        >>> app = main.create_app()
        >>> isinstance(app.name, str)
        True

    """
    app = FastMCP(
        APP_NAME,
        instructions=f"{APP_INSTRUCTIONS} Version: {_server_version()}.",
    )
    _register_tools(app)
    return app


APP = create_app()


if __name__ == "__main__":
    APP.run(transport="stdio")
