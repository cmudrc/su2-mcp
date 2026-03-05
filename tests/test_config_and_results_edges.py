"""Edge-case tests for config and results tool helpers."""

from __future__ import annotations

import base64
from pathlib import Path

from su2_mcp.tools import config_tools, results_tools, session


def test_config_tools_invalid_session_errors() -> None:
    """Config tool helpers should return not_found for missing sessions."""
    assert config_tools.get_config_text("missing")["error"]["type"] == "not_found"
    assert config_tools.parse_config("missing")["error"]["type"] == "not_found"
    assert (
        config_tools.update_config_entries("missing", {})["error"]["type"]
        == "not_found"
    )
    assert config_tools.set_mesh("missing", "bad")["error"]["type"] == "not_found"


def test_set_mesh_without_config_update_still_updates_mesh_filename() -> None:
    """Session-level mesh updates should still synchronize MESH_FILENAME."""
    created = session.create_su2_session(
        initial_config="MESH_FILENAME= initial.su2\n", initial_mesh=None
    )
    session_id = str(created["session_id"])

    mesh_b64 = base64.b64encode(b"NDIME= 3\nNPOIN= 0\nNELEM= 0\n").decode("utf-8")
    updated = config_tools.set_mesh(
        session_id,
        mesh_b64,
        mesh_file_name="replacement.su2",
        update_config=False,
    )

    parsed = config_tools.parse_config(session_id)
    assert Path(str(updated["mesh_path"])).name == "replacement.su2"
    assert parsed["entries"]["MESH_FILENAME"] == "replacement.su2"

    session.close_su2_session(session_id, delete_workdir=True)


def test_results_tools_error_paths_and_filters() -> None:
    """Results helpers should enforce path safety and filtering behavior."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])
    record = session.SESSION_MANAGER.require(session_id)

    history = record.workdir / "history.csv"
    history.write_text(
        "iter,residual,tag\n1,0.1,a\n2,0.01,b\n3,0.001,c\n", encoding="utf-8"
    )

    surface = record.workdir / "surface.csv"
    surface.write_text(
        "marker,cp,temp\nWALL,0.2,300\nFARFIELD,0.1,280\nWALL,0.25,305\n",
        encoding="utf-8",
    )

    listing = results_tools.list_result_files(session_id, extensions=[".csv"])
    assert {entry["path"] for entry in listing["files"]} >= {
        "history.csv",
        "surface.csv",
    }

    outside = results_tools.get_result_file_base64(session_id, "../outside.txt")
    assert outside["error"]["type"] == "validation_error"

    missing = results_tools.get_result_file_base64(session_id, "missing.csv")
    assert missing["error"]["type"] == "not_found"

    subset = results_tools.read_history_csv(
        session_id,
        "history.csv",
        columns=["iter", "residual"],
        max_rows=1,
        skip_rows=1,
    )
    assert subset["columns"] == ["iter", "residual"]
    assert subset["rows"] == [{"iter": 2.0, "residual": 0.01}]

    sample = results_tools.sample_surface_solution(
        session_id,
        "surface.csv",
        marker_name="WALL",
        fields=["cp", "temp"],
        max_points=10,
    )
    assert sample["num_points"] == 2
    assert sample["points"][0] == {"cp": 0.2, "temp": 300.0}

    session.close_su2_session(session_id, delete_workdir=True)


def test_results_tools_missing_file_and_session_errors() -> None:
    """Missing session and file cases should produce not_found errors."""
    assert results_tools.list_result_files("missing")["error"]["type"] == "not_found"
    assert (
        results_tools.read_history_csv("missing", "history.csv")["error"]["type"]
        == "not_found"
    )
    assert (
        results_tools.sample_surface_solution("missing", "surface.csv", None, ["cp"])[
            "error"
        ]["type"]
        == "not_found"
    )

    created = session.create_su2_session()
    session_id = str(created["session_id"])
    assert (
        results_tools.read_history_csv(session_id, "missing.csv")["error"]["type"]
        == "not_found"
    )
    assert (
        results_tools.sample_surface_solution(session_id, "missing.csv", None, ["cp"])[
            "error"
        ]["type"]
        == "not_found"
    )
    session.close_su2_session(session_id, delete_workdir=True)
