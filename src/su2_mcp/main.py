"""Entry point and helpers for the SU2 MCP FastMCP server."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Literal

from mcp.server.fastmcp import FastMCP

from su2_mcp.fastmcp_server import APP_INSTRUCTIONS, APP_NAME, build_server

Transport = Literal["stdio", "sse", "streamable-http"]
TransportInput = Literal["stdio", "sse", "streamable-http", "http"]

TRANSPORT_CHOICES: tuple[TransportInput, ...] = (
    "stdio",
    "sse",
    "streamable-http",
    "http",
)


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for running the SU2 MCP server."""
    parser = argparse.ArgumentParser(description="Run the SU2 MCP server.")
    parser.add_argument(
        "--transport",
        choices=list(TRANSPORT_CHOICES),
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
        "--path",
        default="/mcp",
        help="Base HTTP path for the standard HTTP transport (default: /mcp).",
    )
    parser.add_argument(
        "--streamable-http-path",
        default="/mcp",
        help="Path for the streamable HTTP transport (default: /mcp).",
    )
    parser.add_argument(
        "--mount-path",
        default="/",
        help="Starlette mount path for SSE transport (default: /).",
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
    return parser


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


def _resolve_transport(transport: TransportInput) -> Transport:
    """Map CLI transport input into a FastMCP transport value."""
    if transport == "http":
        return "streamable-http"
    if transport in ("stdio", "sse", "streamable-http"):
        return transport
    msg = f"Unsupported transport: {transport!s}"
    raise ValueError(msg)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the SU2 MCP server with CLI-selected transport settings."""
    parser = build_parser()
    args = parser.parse_args(argv)

    resolved_transport = _resolve_transport(args.transport)
    streamable_path = (
        args.path if args.transport == "http" else args.streamable_http_path
    )
    server = create_app(
        host=args.host,
        port=args.port,
        mount_path=args.mount_path,
        sse_path=args.sse_path,
        message_path=args.message_path,
        streamable_http_path=streamable_path,
    )

    mount_path = args.mount_path if resolved_transport == "sse" else None
    server.run(transport=resolved_transport, mount_path=mount_path)
    return 0


APP = create_app()

__all__ = [
    "APP",
    "APP_INSTRUCTIONS",
    "APP_NAME",
    "TRANSPORT_CHOICES",
    "build_parser",
    "create_app",
    "main",
]
