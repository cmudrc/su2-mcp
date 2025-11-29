"""Lightweight health-check tool for the SU2 MCP server."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class PingRequest(BaseModel):
    """Request payload for the ping tool."""

    message: str | None = Field(
        default=None,
        description="Optional message to echo back in the response.",
    )


class PingResponse(BaseModel):
    """Response payload for the ping tool."""

    ok: bool = Field(default=True, description="Whether the server responded successfully.")
    message: str = Field(
        description="Echoed or default response message used to confirm connectivity.",
    )
    server: str = Field(description="Server identifier providing the response.")
    timestamp: str = Field(description="ISO-8601 UTC timestamp of the response.")


def ping(args: PingRequest) -> PingResponse:
    """Return a simple health check response without requiring SU2.

    The tool intentionally avoids importing SU2 or touching the filesystem so that
    MCP clients can verify connectivity even when SU2 binaries are unavailable.
    """
    now = datetime.now(UTC).isoformat()
    reply = args.message or "pong"
    return PingResponse(message=reply, server="su2-mcp", timestamp=now)


__all__ = ["PingRequest", "PingResponse", "ping"]
