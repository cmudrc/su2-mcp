"""MCP server entrypoint for SU2 integrations."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
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


def create_app(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    mount_path: str = "/",
    sse_path: str = "/sse",
    message_path: str = "/messages/",
    streamable_http_path: str = "/mcp",
    json_response: bool = False,
    stateless_http: bool = False,
) -> FastMCP:
    """Build a FastMCP application with all SU2 tools registered.

    Args:
        host: Host interface on which to bind the HTTP transports.
        port: Network port for HTTP transports.
        mount_path: Base Starlette mount path for HTTP routes.
        sse_path: Path segment for the SSE transport.
        message_path: Path segment for the message transport.
        streamable_http_path: Path segment for the streamable HTTP transport.
        json_response: Whether to emit JSON responses for HTTP transports.
        stateless_http: Whether to run the HTTP server without session state.

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
        host=host,
        port=port,
        mount_path=mount_path,
        sse_path=sse_path,
        message_path=message_path,
        streamable_http_path=streamable_http_path,
        json_response=json_response,
        stateless_http=stateless_http,
    )
    _register_tools(app)
    return app


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the MCP server runner.

    Args:
        argv: Optional list of raw CLI arguments. Defaults to ``None`` to use
            ``sys.argv``.

    Returns:
        Parsed ``argparse`` namespace.

    """
    parser = argparse.ArgumentParser(description="Run the SU2 MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport to expose (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind for HTTP transports (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind for HTTP transports (default: 8000).",
    )
    parser.add_argument(
        "--mount-path",
        default="/",
        help="Starlette mount path for HTTP routes (default: /).",
    )
    parser.add_argument(
        "--sse-path",
        default="/sse",
        help="Path for the SSE transport (default: /sse).",
    )
    parser.add_argument(
        "--message-path",
        default="/messages/",
        help="Path for the message transport (default: /messages/).",
    )
    parser.add_argument(
        "--streamable-http-path",
        default="/mcp",
        help="Path for the streamable HTTP transport (default: /mcp).",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        help="Return JSON responses for HTTP transports (default: False).",
    )
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        help="Run the HTTP server without session state (default: False).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the SU2 MCP server with CLI-selected transport settings.

    Args:
        argv: Optional list of CLI arguments. Defaults to ``None`` to use
            ``sys.argv``.

    """
    args = parse_args(argv)
    app = create_app(
        host=args.host,
        port=args.port,
        mount_path=args.mount_path,
        sse_path=args.sse_path,
        message_path=args.message_path,
        streamable_http_path=args.streamable_http_path,
        json_response=args.json_response,
        stateless_http=args.stateless_http,
    )
    app.run(transport=args.transport)


APP = create_app()


if __name__ == "__main__":
    main()
