"""The mesher takes the STEP by path, the hand-off servers on one machine use."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from su2_mcp import cpacs_adapter
from su2_mcp.tools import mesh_tools, session

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;\n"


def _session():
    created = session.create_su2_session()
    return str(created["session_id"])


def test_step_path_is_read_and_meshed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    sid = _session()
    try:
        step = tmp_path / "aircraft.step"
        step.write_bytes(STEP)
        monkeypatch.setattr(mesh_tools.shutil, "which", lambda _n: "/usr/bin/gmsh")
        seen = {}

        def fake_mesh(step_file, out_mesh, cfg):
            seen["step"] = Path(step_file).read_bytes()
            Path(out_mesh).write_text("NDIME= 3\nNELEM= 0\n")
            return True

        monkeypatch.setattr(cpacs_adapter, "_mesh_step_with_gmsh", fake_mesh)
        out = mesh_tools.generate_mesh_from_step(sid, step_path=str(step))
        assert out["success"] is True
        assert seen["step"] == STEP
    finally:
        session.close_su2_session(sid, delete_workdir=True)


def test_missing_path_and_both_forms_are_typed_errors(tmp_path: Path):
    sid = _session()
    try:
        out = mesh_tools.generate_mesh_from_step(
            sid, step_path=str(tmp_path / "nope.step")
        )
        assert out["error"]["type"] == "invalid_input"
        assert "cad_path" in out["error"]["details"]
        out = mesh_tools.generate_mesh_from_step(
            sid, step_base64=base64.b64encode(STEP).decode(), step_path=str(tmp_path)
        )
        assert out["error"]["type"] == "invalid_input"
        out = mesh_tools.generate_mesh_from_step(sid)
        assert out["error"]["type"] == "invalid_input"
        assert "step_path" in out["error"]["message"]
    finally:
        session.close_su2_session(sid, delete_workdir=True)
