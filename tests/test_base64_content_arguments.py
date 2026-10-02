"""Base64 content arguments refuse file names, paths and URIs with a message
that names what the argument takes.

2026-09-30, a colleague's integration: a small planner passed "mesh.su2" as
initial_mesh and a file:// URI as STEP content; the only message back was
base64's "Incorrect padding".
"""

from __future__ import annotations

import base64

from su2_mcp.tools.config_tools import set_mesh
from su2_mcp.tools.mesh_tools import generate_mesh_from_step
from su2_mcp.tools.session import SESSION_MANAGER, close_su2_session, create_su2_session


def test_filename_as_initial_mesh_is_a_typed_error():
    out = create_su2_session(base_name="t", initial_mesh="mesh.su2")
    assert out["error"]["type"] == "invalid_input"
    assert "initial_mesh" in out["error"]["message"]
    assert "file name" in out["error"]["message"]


def test_file_uri_as_step_base64_is_a_typed_error():
    rec = SESSION_MANAGER.create_session(base_name="t2")
    try:
        out = generate_mesh_from_step(
            session_id=rec.session_id,
            step_base64="file:///Users/x/aircraft.xml",
        )
        assert out["error"]["type"] == "invalid_input"
        assert "cad_base64" in out["error"]["message"]
    finally:
        close_su2_session(rec.session_id, delete_workdir=True)


def test_real_base64_still_works():
    mesh = base64.b64encode(b"NDIME= 3\nNELEM= 0\n").decode()
    out = create_su2_session(base_name="t3", initial_mesh=mesh)
    assert "error" not in out
    close_su2_session(out["session_id"], delete_workdir=True)


def test_set_mesh_rejects_path_like_value():
    rec = SESSION_MANAGER.create_session(base_name="t4")
    try:
        out = set_mesh(rec.session_id, mesh_base64="./meshes/mesh.su2")
        assert out["error"]["type"] == "invalid_input"
    finally:
        close_su2_session(rec.session_id, delete_workdir=True)


def test_empty_gmsh_output_is_an_error(monkeypatch, tmp_path):
    """gmsh can exit 0 with an empty file when the .geo fails mid-script."""
    import base64 as _b64
    import subprocess

    from su2_mcp.tools import mesh_tools

    rec = SESSION_MANAGER.create_session(base_name="t5")
    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _n: "/usr/bin/gmsh")

    def fake_run(cmd, cwd, capture_output, text, timeout):
        # find "-o <path>" and write an empty file, exit 0
        out = cmd[cmd.index("-o") + 1]
        open(out, "wb").close()
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(mesh_tools.subprocess, "run", fake_run)
    step = _b64.b64encode(b"ISO-10303-21; fake step").decode()
    geo = tmp_path / "t.geo"
    geo.write_text("// template")
    try:
        # The CLI path (custom template) is where gmsh's exit code is trusted.
        out = mesh_tools.generate_mesh_from_step(
            rec.session_id, step, geo_template_path=str(geo)
        )
        assert out["error"]["type"] == "runtime_error"
        assert "NDIME" in out["error"]["message"]
    finally:
        close_su2_session(rec.session_id, delete_workdir=True)


def test_step_bytes_as_initial_mesh_are_refused():
    """A CAD file is not a mesh, even when its base64 decodes cleanly."""
    import base64 as _b64

    step = _b64.b64encode(b"ISO-10303-21;\nHEADER;").decode()
    out = create_su2_session(base_name="t6", initial_mesh=step)
    assert out["error"]["type"] == "invalid_input"
    assert "generate_mesh_from_step" in out["error"]["message"]


def test_real_su2_mesh_bytes_still_accepted():
    import base64 as _b64

    mesh = _b64.b64encode(b"NDIME= 3\nNELEM= 0\n").decode()
    out = create_su2_session(base_name="t7", initial_mesh=mesh)
    assert "error" not in out
    close_su2_session(out["session_id"], delete_workdir=True)


def test_output_mesh_name_gets_su2_suffix(monkeypatch, tmp_path):
    import base64 as _b64
    import subprocess

    from su2_mcp.tools import mesh_tools

    rec = SESSION_MANAGER.create_session(base_name="t8")
    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _n: "/usr/bin/gmsh")
    seen = {}

    def fake_run(cmd, cwd, capture_output, text, timeout):
        out = cmd[cmd.index("-o") + 1]
        seen["out"] = out
        with open(out, "wb") as fh:
            fh.write(b"NDIME= 3\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(mesh_tools.subprocess, "run", fake_run)
    geo = tmp_path / "t.geo"; geo.write_text("// template")
    step = _b64.b64encode(b"ISO-10303-21; x").decode()
    out = mesh_tools.generate_mesh_from_step(rec.session_id, step, output_mesh_name="canards_mesh", geo_template_path=str(geo))
    assert seen["out"].endswith("canards_mesh.su2")
    assert out["success"] is True
    close_su2_session(rec.session_id, delete_workdir=True)


def test_physics_name_as_solver_binary_is_refused():
    """'EULER' is a physics setting, not an executable."""
    from su2_mcp.tools.run_tools import run_su2_solver

    rec = SESSION_MANAGER.create_session(base_name="t9")
    try:
        out = run_su2_solver(rec.session_id, solver="EULER")
        assert out["error"]["type"] == "invalid_input"
        assert "SU2_CFD" in out["error"]["message"]
        assert "config" in out["error"]["message"]
    finally:
        close_su2_session(rec.session_id, delete_workdir=True)


def test_small_farfield_factor_is_refused():
    """farfield_factor=1 puts the farfield on the aircraft; refuse it."""
    import pytest as _pytest

    from su2_mcp.cpacs_adapter import run_adapter

    cpacs = (
        "<cpacs><vehicles><aircraft><model>"
        "<reference><area>1.0</area><length>1.0</length></reference>"
        "</model></aircraft></vehicles></cpacs>"
    )
    with _pytest.raises(ValueError, match="farfield_factor must be >= 2"):
        run_adapter(cpacs, mesh_path="x.su2", farfield_factor=1.0)


def test_nested_config_values_are_refused():
    """A dict value would be written as its Python repr into the SU2 config."""
    from su2_mcp.tools.config_tools import update_config_entries

    rec = SESSION_MANAGER.create_session(base_name="t10")
    try:
        out = update_config_entries(rec.session_id, {"MACH_NUMBER": {"value": "0.78"}})
        assert out["error"]["type"] == "invalid_input"
        assert "scalars" in out["error"]["message"]
        ok = update_config_entries(rec.session_id, {"MACH_NUMBER": 0.78, "AOA": 2.0})
        assert sorted(ok["updated_keys"]) == ["AOA", "MACH_NUMBER"]
    finally:
        close_su2_session(rec.session_id, delete_workdir=True)
