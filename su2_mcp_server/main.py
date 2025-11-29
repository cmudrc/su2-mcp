"""Programmatic helpers for constructing the SU2 MCP FastMCP server."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from su2_mcp_server.fastmcp_server import APP_INSTRUCTIONS, APP_NAME, build_server


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
    """Build a FastMCP application with all SU2 tools registered."""

    server = build_server()
    server.settings.host = host
    server.settings.port = port
    server.settings.mount_path = mount_path
    server.settings.sse_path = sse_path
    server.settings.message_path = message_path
    server.settings.streamable_http_path = streamable_http_path
    server.settings.json_response = json_response
    server.settings.stateless_http = stateless_http
    return server


APP = create_app()

__all__ = ["APP", "APP_INSTRUCTIONS", "APP_NAME", "create_app"]
