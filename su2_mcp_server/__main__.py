"""Command-line entrypoint for running the SU2 MCP server."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Literal

from mcp.server.fastmcp import FastMCP

from su2_mcp_server.fastmcp_server import build_server

Transport = Literal["stdio", "sse", "streamable-http"]
TransportInput = Literal["stdio", "sse", "streamable-http", "http"]

TRANSPORT_CHOICES: tuple[TransportInput, ...] = (
    "stdio",
    "sse",
    "streamable-http",
    "http",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the MCP server runner."""
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
    return parser.parse_args(argv)


def _apply_settings(args: argparse.Namespace) -> tuple[Transport, str | None, FastMCP]:
    """Create and configure the FastMCP server for the requested transport.

    Returns a tuple of the resolved transport identifier, the mount path (when
    applicable), and the configured server instance ready to run.
    """
    server = build_server()
    server.settings.host = args.host
    server.settings.port = args.port
    server.settings.mount_path = args.mount_path
    server.settings.sse_path = args.sse_path
    server.settings.message_path = args.message_path

    transport: Transport
    if args.transport == "http":
        transport = "streamable-http"
    elif args.transport in ("stdio", "sse", "streamable-http"):
        transport = args.transport
    else:  # pragma: no cover - argparse choices prevent this path
        msg = f"Unsupported transport: {args.transport!s}"
        raise ValueError(msg)
    mount_path = args.mount_path if transport == "sse" else None

    if transport == "streamable-http":
        path = args.path if args.transport == "http" else args.streamable_http_path
        server.settings.streamable_http_path = path

    return transport, mount_path, server


def main(argv: Sequence[str] | None = None) -> None:
    """Run the SU2 MCP server with CLI-selected transport settings."""
    args = parse_args(argv)
    transport, mount_path, server = _apply_settings(args)
    server.run(transport=transport, mount_path=mount_path)


if __name__ == "__main__":
    main()
