"""Session-oriented MCP tools."""

from __future__ import annotations

from su2_mcp_server.session_manager import SessionManager

SESSION_MANAGER = SessionManager()


def _error(
    message: str, error_type: str = "runtime_error", details: object | None = None
) -> dict[str, object]:
    """Standardized error response payload."""
    return {"error": {"type": error_type, "message": message, "details": details}}


def create_su2_session(
    base_name: str | None = None,
    initial_config: str | None = None,
    initial_mesh: str | None = None,
    mesh_file_name: str = "mesh.su2",
) -> dict[str, object]:
    """Create a new SU2 session and return basic paths."""
    try:
        record = SESSION_MANAGER.create_session(
            base_name=base_name,
            initial_config=initial_config,
            initial_mesh=initial_mesh,
            mesh_file_name=mesh_file_name,
        )
        return {
            "session_id": record.session_id,
            "workdir": str(record.workdir),
            "config_path": str(record.config_path),
            "mesh_path": str(record.mesh_path) if record.mesh_path else None,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return _error("Failed to create SU2 session", details=str(exc))


def close_su2_session(session_id: str, delete_workdir: bool = False) -> dict[str, object]:
    """Close a session and optionally delete its working directory."""
    try:
        success = SESSION_MANAGER.close_session(session_id, delete_workdir=delete_workdir)
        return {"success": success}
    except Exception as exc:  # pragma: no cover
        return _error("Failed to close session", details=str(exc))


def get_session_info(session_id: str) -> dict[str, object]:
    """Return session paths and last run metadata."""
    try:
        return SESSION_MANAGER.to_info(session_id)
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to read session info", details=str(exc))


__all__ = [
    "create_su2_session",
    "close_su2_session",
    "get_session_info",
    "SESSION_MANAGER",
]
