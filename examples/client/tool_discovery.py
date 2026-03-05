"""List the current SU2 MCP tools using the in-process FastMCP app."""

from __future__ import annotations

import asyncio
import json

from su2_mcp.fastmcp_server import build_server


async def _main() -> None:
    """Run asynchronous discovery and print a stable JSON payload."""
    app = build_server()
    tools = await app.list_tools()
    payload = {
        "tool_count": len(tools),
        "tool_names": sorted(tool.name for tool in tools),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main())
