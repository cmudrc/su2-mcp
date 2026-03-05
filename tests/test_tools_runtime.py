"""Runtime coverage for deterministic SU2 session/config/results tool behavior."""

from __future__ import annotations

import base64
from pathlib import Path

from su2_mcp.tools import config_tools, results_tools, run_tools, session


def test_session_creation_with_mesh_and_config_parsing(
    sample_config_text: str,
    sample_mesh_base64: str,
) -> None:
    """Creating a session with seed config/mesh preserves paths and parsed keys."""
    created = session.create_su2_session(
        initial_config=sample_config_text,
        initial_mesh=sample_mesh_base64,
        mesh_file_name="initial_mesh.su2",
    )
    assert "error" not in created

    session_id = str(created["session_id"])
    info = session.get_session_info(session_id)
    parsed = config_tools.parse_config(session_id)

    mesh_path = Path(str(info["mesh_path"]))
    assert mesh_path.exists()
    assert parsed["entries"]["MESH_FILENAME"] == "initial_mesh.su2"
    assert parsed["entries"]["CFL_NUMBER"] == 5.0

    closed = session.close_su2_session(session_id, delete_workdir=True)
    assert closed["success"] is True


def test_update_config_entries_round_trip(sample_config_text: str) -> None:
    """Config entries can be updated and read back through MCP tools."""
    created = session.create_su2_session(initial_config=sample_config_text)
    session_id = str(created["session_id"])

    update = config_tools.update_config_entries(
        session_id,
        {"CFL_NUMBER": 7, "NEW_KEY": True},
        create_if_missing=True,
    )
    parsed = config_tools.parse_config(session_id)
    raw = config_tools.get_config_text(session_id)

    assert set(update["updated_keys"]) == {"CFL_NUMBER", "NEW_KEY"}
    assert parsed["entries"]["CFL_NUMBER"] == 7
    assert parsed["entries"]["NEW_KEY"] is True
    assert "NEW_KEY= TRUE" in str(raw["config_text"])

    session.close_su2_session(session_id, delete_workdir=True)


def test_run_solver_missing_binary_returns_structured_error() -> None:
    """Missing solver binaries surface stable error metadata."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    result = run_tools.run_su2_solver(session_id=session_id, solver="missing_solver")

    assert result["success"] is False
    assert result["error"]["type"] == "missing_binary"
    assert result["exit_code"] == -1

    session.close_su2_session(session_id, delete_workdir=True)


def test_result_file_listing_and_history_parsing() -> None:
    """Result helpers list files, parse history CSV, and encode payload slices."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])
    record = session.SESSION_MANAGER.require(session_id)

    history_path = record.workdir / "history.csv"
    history_path.write_text("iter,residual\n1,0.1\n2,0.01\n", encoding="utf-8")

    listing = results_tools.list_result_files(session_id)
    history = results_tools.read_history_csv(session_id, "history.csv")
    encoded = results_tools.get_result_file_base64(
        session_id, "history.csv", max_bytes=10
    )

    assert any(entry["path"] == "history.csv" for entry in listing["files"])
    assert history["rows"][0]["residual"] == 0.1
    assert encoded["truncated"] is True
    assert base64.b64decode(encoded["data_base64"]).startswith(b"iter,resid")

    session.close_su2_session(session_id, delete_workdir=True)
