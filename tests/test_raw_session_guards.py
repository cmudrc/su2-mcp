"""A raw session starts from the preset's settings, and the solver tool refuses
an incomplete force-coefficient setup (2026-10-08, Kiro Mode A runs A6/AS3/AS4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from su2_mcp.config_seed import (
    REQUIRED_FOR_SU2_CFD,
    missing_required_keys,
    seed_config_text,
)
from su2_mcp.config_utils import parse_config_text
from su2_mcp.cpacs_adapter import _write_euler_config
from su2_mcp.tools import config_tools, run_tools, session


def _fresh_session() -> str:
    return str(session.create_su2_session(base_name="guard")["session_id"])


def test_seeded_config_has_preset_numerics_and_no_case() -> None:
    sid = _fresh_session()
    text = Path(session.get_session_info(sid)["config_path"]).read_text()
    entries = parse_config_text(text)
    assert entries["MARKER_MONITORING"] == "( WALL )"
    assert (
        entries["MARKER_EULER"] == "( WALL )"
        and entries["MARKER_FAR"] == "( FARFIELD )"
    )
    assert entries["ITER"] == 250 and entries["CONV_NUM_METHOD_FLOW"] == "ROE"
    assert "LIFT" in str(entries["SCREEN_OUTPUT"]) and "DRAG" in str(
        entries["HISTORY_OUTPUT"]
    )
    for key in ("MACH_NUMBER", "AOA", "REF_AREA"):
        assert key not in entries, key  # only mentioned in comments
    assert missing_required_keys(entries) == ["MACH_NUMBER", "AOA", "REF_AREA"]
    session.close_su2_session(sid, delete_workdir=True)


def test_seed_matches_the_preset_path_numerics(tmp_path: Path) -> None:
    """The seed and the validated preset path share every numerics key."""
    cfg = tmp_path / "preset.cfg"
    _write_euler_config(
        cfg,
        {"mach": 0.78, "aoa_deg": 2.0, "ref_length_m": 1.0, "ref_area_m2": 1.0},
        "mesh.su2",
        iter_cap=250,
    )
    preset = parse_config_text(cfg.read_text())
    seed = parse_config_text(seed_config_text("mesh.su2"))
    shared = [k for k in preset if k in seed]
    assert {
        "CFL_NUMBER",
        "CONV_NUM_METHOD_FLOW",
        "MUSCL_FLOW",
        "ITER",
        "CONV_RESIDUAL_MINVAL",
        "MARKER_MONITORING",
        "HISTORY_OUTPUT",
        "SCREEN_OUTPUT",
    } <= set(shared)
    for k in shared:
        assert preset[k] == seed[k], k
    assert set(preset) - set(seed) == {
        "MACH_NUMBER",
        "AOA",
        "REF_AREA",
        "REF_LENGTH",
        "REF_ORIGIN_MOMENT_X",
        "REF_ORIGIN_MOMENT_Y",
        "REF_ORIGIN_MOMENT_Z",
    }


def test_initial_config_still_overrides_the_seed() -> None:
    sid = str(
        session.create_su2_session(
            initial_config="MESH_FILENAME= m.su2\nSOLVER= EULER\n"
        )["session_id"]
    )
    assert (
        "MARKER_MONITORING"
        not in Path(session.get_session_info(sid)["config_path"]).read_text()
    )
    session.close_su2_session(sid, delete_workdir=True)


def test_solver_refuses_when_case_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NeverRun:
        def __init__(self, workdir: Path) -> None: ...

        def run(self, *a: object, **k: object) -> dict[str, object]:
            raise AssertionError("SU2 must not be launched with an incomplete config")

    monkeypatch.setattr(run_tools, "SU2Runner", _NeverRun)
    sid = _fresh_session()
    out = run_tools.run_su2_solver(sid)
    assert out["error"]["type"] == "config_incomplete"
    assert out["error"]["details"]["missing"] == ["MACH_NUMBER", "AOA", "REF_AREA"]
    assert out["error"]["details"]["required"] == list(REQUIRED_FOR_SU2_CFD)
    assert "Nothing was run" in out["error"]["message"]
    session.close_su2_session(sid, delete_workdir=True)


def test_solver_refuses_without_monitoring_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NeverRun:
        def __init__(self, workdir: Path) -> None: ...

        def run(self, *a: object, **k: object) -> dict[str, object]:
            raise AssertionError("SU2 must not be launched without MARKER_MONITORING")

    monkeypatch.setattr(run_tools, "SU2Runner", _NeverRun)
    # The AS3 configuration of 2026-10-08, as the model wrote it.
    sid = str(
        session.create_su2_session(
            initial_config=(
                "MESH_FILENAME= mesh.su2\nMACH_NUMBER= 0.78\nAOA= 2.0\n"
                "MATH_PROBLEM= DIRECT\nSOLVER= EULER\nREF_LENGTH= 1.0\n"
                "REF_AREA= 1.0\nMARKER_EULER= ( WALL )\n"
                "MARKER_FAR= ( FARFIELD )\nCONV_NUM_METHOD_FLOW= ROE\n"
            )
        )["session_id"]
    )
    out = run_tools.run_su2_solver(sid)
    assert out["error"]["type"] == "config_incomplete"
    assert out["error"]["details"]["missing"] == ["MARKER_MONITORING"]
    config_tools.update_config_entries(sid, {"MARKER_MONITORING": "NONE"})
    assert run_tools.run_su2_solver(sid)["error"]["details"]["missing"] == [
        "MARKER_MONITORING"
    ]
    session.close_su2_session(sid, delete_workdir=True)


def test_solver_runs_once_the_case_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    launched: dict[str, object] = {}

    class _FakeRunner:
        def __init__(self, workdir: Path) -> None: ...

        def run(self, solver: str, config_path: Path, *a: object) -> dict[str, object]:
            launched["config"] = parse_config_text(Path(config_path).read_text())
            return {
                "success": True,
                "solver": solver,
                "config_used": str(config_path),
                "exit_code": 0,
                "runtime_seconds": 1.0,
                "log_tail": "",
                "residual_history": [],
            }

    monkeypatch.setattr(run_tools, "SU2Runner", _FakeRunner)
    sid = _fresh_session()
    config_tools.update_config_entries(
        sid, {"MACH_NUMBER": 0.78, "AOA": 2.0, "REF_AREA": 1.0}
    )
    out = run_tools.run_su2_solver(sid)
    assert out["success"] is True
    assert (
        launched["config"]["MARKER_MONITORING"] == "( WALL )"
        and launched["config"]["MACH_NUMBER"] == 0.78
    )
    session.close_su2_session(sid, delete_workdir=True)


def test_override_skips_the_check_and_su2_def_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _FakeRunner:
        def __init__(self, workdir: Path) -> None: ...

        def run(self, solver: str, config_path: Path, *a: object) -> dict[str, object]:
            calls.append(solver)
            return {
                "success": True,
                "solver": solver,
                "config_used": str(config_path),
                "exit_code": 0,
                "runtime_seconds": 1.0,
                "log_tail": "",
                "residual_history": [],
            }

    monkeypatch.setattr(run_tools, "SU2Runner", _FakeRunner)
    sid = _fresh_session()
    assert (
        run_tools.run_su2_solver(sid, allow_incomplete_config=True)["success"] is True
    )
    assert run_tools.run_su2_solver(sid, solver="SU2_DEF")["success"] is True
    assert calls == ["SU2_CFD", "SU2_DEF"]
    session.close_su2_session(sid, delete_workdir=True)
