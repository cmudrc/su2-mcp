"""Integration-style tests for session lifecycle and tooling."""

import base64
from pathlib import Path
from typing import cast

import pytest

from su2_mcp_server.tools import results_tools, run_tools, session


def test_session_creation_with_mesh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Creating a session with a mesh writes files and config metadata."""
    dummy_mesh = b"mesh data"
    mesh_b64 = base64.b64encode(dummy_mesh).decode()
    created = session.create_su2_session(initial_config=None, initial_mesh=mesh_b64)
    assert "error" not in created
    session_id = cast(str, created["session_id"])

    mesh_path_raw = created["mesh_path"]
    assert isinstance(mesh_path_raw, str)
    mesh_path = Path(mesh_path_raw)
    assert mesh_path.exists()

    info = session.get_session_info(session_id)
    assert info["mesh_path"] == str(mesh_path)

    config_path_value = cast(str, info["config_path"])
    config_contents = Path(config_path_value).read_text()
    assert "MESH_FILENAME" in config_contents

    session.close_su2_session(session_id, delete_workdir=True)


def test_run_solver_missing_binary_returns_error() -> None:
    """Running with a missing solver binary surfaces an error payload."""
    created = session.create_su2_session()
    session_id = cast(str, created["session_id"])
    result = run_tools.run_su2_solver(session_id=session_id, solver="missing_solver")
    assert "error" in result
    error_payload = cast(dict[str, object], result["error"])
    assert error_payload["type"] == "missing_binary"
    session.close_su2_session(session_id, delete_workdir=True)


def test_result_file_roundtrip(tmp_path: Path) -> None:
    """Result file helpers list, parse, and export history data."""
    created = session.create_su2_session()
    session_id = cast(str, created["session_id"])
    record = session.SESSION_MANAGER.require(session_id)
    sample_file = record.workdir / "history.csv"
    sample_file.write_text("iter,residual\n1,0.1\n2,0.01\n")

    listing = results_tools.list_result_files(session_id)
    files = cast(list[dict[str, object]], listing.get("files", []))
    assert any(entry.get("path") == "history.csv" for entry in files)

    history = results_tools.read_history_csv(session_id, "history.csv")
    rows = cast(list[dict[str, object]], history.get("rows", []))
    residual = cast(float, rows[0]["residual"])
    assert residual == 0.1

    encoded = results_tools.get_result_file_base64(session_id, "history.csv", max_bytes=10)
    assert encoded.get("truncated") is True
    session.close_su2_session(session_id, delete_workdir=True)
