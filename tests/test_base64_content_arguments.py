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
    mesh = base64.b64encode(b"fake mesh bytes").decode()
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
