"""Focused tests for solver tool wrappers and metadata behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from su2_mcp.session_manager import LastRunMetadata
from su2_mcp.tools import run_tools, session


def test_run_su2_solver_records_last_run_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful runs should persist converted metadata in session state."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    captured: dict[str, object] = {}

    class _FakeRunner:
        def __init__(self, workdir: Path) -> None:
            captured["workdir"] = workdir

        def run(
            self,
            solver: str,
            config_path: Path,
            max_runtime_seconds: int,
            capture_log_lines: int,
        ) -> dict[str, object]:
            captured.update(
                {
                    "solver": solver,
                    "config_path": config_path,
                    "max_runtime_seconds": max_runtime_seconds,
                    "capture_log_lines": capture_log_lines,
                }
            )
            return {
                "success": True,
                "solver": solver,
                "config_used": str(config_path),
                "exit_code": "0",
                "runtime_seconds": "2.5",
                "log_tail": "done",
                "residual_history": [],
            }

    monkeypatch.setattr(run_tools, "SU2Runner", _FakeRunner)

    result = run_tools.run_su2_solver(
        session_id=session_id,
        solver="SU2_CFD",
        max_runtime_seconds=123,
        capture_log_lines=7,
    )

    assert result["success"] is True
    assert captured["solver"] == "SU2_CFD"
    assert captured["max_runtime_seconds"] == 123
    assert captured["capture_log_lines"] == 7

    info = session.get_session_info(session_id)
    last_run = info["last_run"]
    assert isinstance(last_run, dict)
    assert last_run["solver"] == "SU2_CFD"
    assert last_run["exit_code"] == 0
    assert last_run["runtime_seconds"] == pytest.approx(2.5)

    session.close_su2_session(session_id, delete_workdir=True)


def test_run_su2_solver_with_override_path_and_error_does_not_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error payloads should pass through without overwriting last_run metadata."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    record = session.SESSION_MANAGER.require(session_id)
    record.last_run_metadata = LastRunMetadata(
        solver="old",
        config_used="old.cfg",
        exit_code=0,
        runtime_seconds=1.0,
        log_tail="old",
    )

    class _FakeRunner:
        def __init__(self, _workdir: Path) -> None:
            return

        def run(
            self,
            solver: str,
            config_path: Path,
            max_runtime_seconds: int,
            capture_log_lines: int,
        ) -> dict[str, object]:
            del solver, max_runtime_seconds, capture_log_lines
            assert config_path.name == "override.cfg"
            return {
                "success": False,
                "solver": "SU2_CFD",
                "config_used": str(config_path),
                "exit_code": -1,
                "runtime_seconds": 0.1,
                "log_tail": "",
                "error": {"type": "missing_binary", "message": "missing"},
            }

    monkeypatch.setattr(run_tools, "SU2Runner", _FakeRunner)

    result = run_tools.run_su2_solver(
        session_id=session_id,
        config_override_path="override.cfg",
    )

    assert result["success"] is False
    info = session.get_session_info(session_id)
    last_run = info["last_run"]
    assert isinstance(last_run, dict)
    assert last_run["solver"] == "old"

    session.close_su2_session(session_id, delete_workdir=True)


def test_run_su2_solver_invalid_session_returns_not_found() -> None:
    """Missing sessions should map to the standard not_found error envelope."""
    result = run_tools.run_su2_solver(session_id="missing")
    assert result["error"]["type"] == "not_found"


def test_generate_deformed_mesh_success_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SU2_DEF wrapper should normalize result types and propagate errors."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    calls: list[dict[str, object]] = []

    class _FakeRunner:
        def __init__(self, _workdir: Path) -> None:
            return

        def run(
            self,
            solver: str,
            config_path: Path,
            max_runtime_seconds: int,
            capture_log_lines: int,
        ) -> dict[str, object]:
            calls.append(
                {
                    "solver": solver,
                    "config_path": config_path,
                    "max_runtime_seconds": max_runtime_seconds,
                    "capture_log_lines": capture_log_lines,
                }
            )
            if len(calls) == 1:
                return {
                    "success": True,
                    "exit_code": "0",
                    "runtime_seconds": "3.5",
                    "log_tail": "ok",
                }
            return {
                "success": False,
                "exit_code": "-1",
                "runtime_seconds": "0.2",
                "log_tail": "bad",
                "error": {"type": "missing_binary", "message": "missing"},
            }

    monkeypatch.setattr(run_tools, "SU2Runner", _FakeRunner)

    success = run_tools.generate_deformed_mesh(
        session_id=session_id,
        def_config_path="def.cfg",
        output_mesh_name="mesh_def.su2",
        max_runtime_seconds=77,
    )
    failure = run_tools.generate_deformed_mesh(session_id=session_id)

    assert calls[0] == {
        "solver": "SU2_DEF",
        "config_path": session.SESSION_MANAGER.require(session_id).workdir / "def.cfg",
        "max_runtime_seconds": 77,
        "capture_log_lines": 200,
    }
    assert success["success"] is True
    assert success["exit_code"] == 0
    assert success["runtime_seconds"] == pytest.approx(3.5)
    assert str(success["deformed_mesh_path"]).endswith("mesh_def.su2")

    assert failure["success"] is False
    assert failure["deformed_mesh_path"] is None
    assert failure["error"]["type"] == "missing_binary"

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_deformed_mesh_invalid_session_returns_not_found() -> None:
    """Missing sessions should map to the standard not_found error envelope."""
    result = run_tools.generate_deformed_mesh(session_id="missing")
    assert result["error"]["type"] == "not_found"
