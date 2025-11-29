"""Configuration-related MCP tools."""

from __future__ import annotations

from typing import Any

from su2_mcp_server import config_utils
from su2_mcp_server.tools.session import SESSION_MANAGER, _error


def get_config_text(session_id: str) -> dict[str, object]:
    """Return raw config text for the session."""
    try:
        record = SESSION_MANAGER.require(session_id)
        return {"config_text": record.config_path.read_text()}
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to read config", details=str(exc))


def parse_config(session_id: str) -> dict[str, object]:
    """Parse the session configuration into key/value entries."""
    try:
        record = SESSION_MANAGER.require(session_id)
        entries = config_utils.parse_config_file(record.config_path)
        return {"entries": entries}
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to parse config", details=str(exc))


def update_config_entries(
    session_id: str,
    updates: dict[str, Any],
    create_if_missing: bool = True,
) -> dict[str, object]:
    """Update configuration entries for a session."""
    try:
        record = SESSION_MANAGER.require(session_id)
        updated = config_utils.update_config_entries(
            record.config_path, updates, create_if_missing=create_if_missing
        )
        return {"updated_keys": updated}
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to update config", details=str(exc))


def set_mesh(
    session_id: str,
    mesh_base64: str,
    mesh_file_name: str = "mesh.su2",
    update_config: bool = True,
) -> dict[str, object]:
    """Persist a mesh file for the session and update the config."""
    try:
        mesh_path = SESSION_MANAGER.update_mesh(session_id, mesh_base64, mesh_file_name)
        if update_config:
            config_utils.update_config_entries(
                SESSION_MANAGER.require(session_id).config_path, {"MESH_FILENAME": mesh_file_name}
            )
        return {"mesh_path": str(mesh_path)}
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to set mesh", details=str(exc))


__all__ = [
    "get_config_text",
    "parse_config",
    "update_config_entries",
    "set_mesh",
]
