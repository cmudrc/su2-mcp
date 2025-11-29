"""MCP server entrypoint for SU2 integrations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mcp.server import Server
from mcp.server.jsonrpc import AsyncJsonRpcTransport  # type: ignore[import-not-found]

from su2_mcp_server.tools import config_tools, results_tools, run_tools, session

SERVER: Any = Server("su2-mcp")


def _register_tool(name: str, func: Callable[..., dict[str, object]]) -> None:
    SERVER.register_tool(name=name, func=func)


# Session tools
_register_tool("create_su2_session", session.create_su2_session)
_register_tool("close_su2_session", session.close_su2_session)
_register_tool("get_session_info", session.get_session_info)

# Config tools
_register_tool("get_config_text", config_tools.get_config_text)
_register_tool("parse_config", config_tools.parse_config)
_register_tool("update_config_entries", config_tools.update_config_entries)
_register_tool("set_mesh", config_tools.set_mesh)

# Run tools
_register_tool("run_su2_solver", run_tools.run_su2_solver)
_register_tool("generate_deformed_mesh", run_tools.generate_deformed_mesh)

# Result tools
_register_tool("list_result_files", results_tools.list_result_files)
_register_tool("get_result_file_base64", results_tools.get_result_file_base64)
_register_tool("read_history_csv", results_tools.read_history_csv)
_register_tool("sample_surface_solution", results_tools.sample_surface_solution)


async def serve(transport: AsyncJsonRpcTransport) -> None:
    """Serve registered tools using the provided transport."""
    await SERVER.serve(transport)


if __name__ == "__main__":
    from mcp.server.stdio import stdio_transport  # type: ignore[attr-defined]

    asyncio.run(serve(stdio_transport()))
