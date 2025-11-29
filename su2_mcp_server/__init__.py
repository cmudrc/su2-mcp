"""SU2 MCP server package."""

from su2_mcp_server.fastmcp_server import APP_INSTRUCTIONS, APP_NAME, build_server
from su2_mcp_server.session_manager import SessionManager, SessionRecord

__all__ = ["APP_INSTRUCTIONS", "APP_NAME", "SessionManager", "SessionRecord", "build_server"]
