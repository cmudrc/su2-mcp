"""gmsh runs in a child process, so a crash inside gmsh is a structured error.

Found 2026-11-23: on one aircraft at surface_density 20, gmsh printed
"Illegal hash-positionPosition: 13,12,0" and took a segmentation fault. The
mesher ran inside the MCP server, the server ended, and every later tool
answered "Server session was closed unexpectedly".

The crash itself cannot be produced on demand (it needs that geometry and
does not happen on every run), so the tests that need a dying mesher replace
the child's command with a process that prints the same line and aborts.
Everything else here runs the real gmsh.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from su2_mcp import cpacs_adapter, mesh_child
from su2_mcp.tools import mesh_tools, session

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;\n"
SRC = str(Path(mesh_child.__file__).resolve().parents[1])

_PRINT = (
    "import sys; sys.stderr.write('Illegal hash-positionPosition: 13,12,0\\n'); "
    "sys.stderr.flush(); "
)
DYING = {
    "abort": (_PRINT + "import os; os.abort()", "signal SIGABRT"),
    "segfault": (_PRINT + "import ctypes; ctypes.string_at(0)", "signal SIGSEGV"),
    "exit": (_PRINT + "raise SystemExit(3)", "exit code 3"),
}


def _dying_child(code: str):
    def command(step_path, su2_path, cfg_json, result_path):
        # like a real crash part-way: something was written, no result
        Path(su2_path).write_text("NDIME= 3\n")
        return [sys.executable, "-c", code]

    return command


def _session() -> str:
    return str(session.create_su2_session()["session_id"])


def _box_step(path: Path) -> None:
    gmsh = pytest.importorskip("gmsh")
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.occ.addBox(0, 0, 0, 2.0, 1.0, 1.0)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


@pytest.mark.skipif(os.name == "nt", reason="signal names are POSIX")
@pytest.mark.parametrize("how", sorted(DYING))
def test_a_dying_mesher_is_a_structured_error(monkeypatch, tmp_path, how):
    code, ending = DYING[how]
    monkeypatch.setattr(mesh_child, "_child_command", _dying_child(code))
    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _n: "/usr/bin/gmsh")
    step = tmp_path / "aircraft.step"
    step.write_bytes(STEP)
    sid = _session()
    try:
        out = mesh_tools.generate_mesh_from_step(
            sid, step_path=str(step), surface_density=20
        )
        error = out["error"]
        assert error["type"] == "mesh_generation_failed"
        assert "surface_density=20" in error["message"]
        assert "farfield_factor=10.0" in error["message"]
        assert ending in error["message"]
        assert "Illegal hash-positionPosition: 13,12,0" in error["message"]
        assert error["details"]["surface_density"] == 20
        # this process is still here, and so is the session, with no mesh
        info = session.get_session_info(sid)
        assert "error" not in info
        assert info["mesh_path"] is None
    finally:
        session.close_su2_session(sid, delete_workdir=True)


def test_a_dying_mesher_names_the_absolute_size(monkeypatch, tmp_path):
    code, _ = DYING["exit"]
    monkeypatch.setattr(mesh_child, "_child_command", _dying_child(code))
    out = tmp_path / "m.su2"
    outcome = mesh_child.run_mesh_in_child(
        "x.step", str(out), {"surface_size_m": 0.35, "farfield_factor": 8.0}
    )
    assert outcome.crashed and not outcome.ok
    assert "surface_size_m=0.35, farfield_factor=8.0" in outcome.reason
    # the partly written mesh is gone
    assert not out.exists()


def test_a_mesh_from_a_process_that_then_dies_is_discarded(monkeypatch, tmp_path):
    def command(step_path, su2_path, cfg_json, result_path):
        code = (
            "import json, sys; open(sys.argv[1], 'w').write('NDIME= 3\\n'); "
            "json.dump({'ok': True}, open(sys.argv[2], 'w')); raise SystemExit(9)"
        )
        return [sys.executable, "-c", code, su2_path, result_path]

    monkeypatch.setattr(mesh_child, "_child_command", command)
    out = tmp_path / "m.su2"
    outcome = mesh_child.run_mesh_in_child("x.step", str(out), {})
    assert outcome.crashed and not outcome.ok
    assert "exit code 9" in outcome.reason and "discarded" in outcome.reason
    assert not out.exists()


def test_run_adapter_reports_a_dying_mesher(monkeypatch, tmp_path):
    """The one-call CFD route (the gateway calls it in its own process)."""
    code, _ = DYING["exit"]
    monkeypatch.setattr(mesh_child, "_child_command", _dying_child(code))
    step = tmp_path / "aircraft.step"
    step.write_bytes(STEP)
    cpacs = (
        "<?xml version='1.0'?><cpacs><vehicles><aircraft><model>"
        "<reference><area>1.0</area><length>1.0</length></reference>"
        "</model></aircraft></vehicles></cpacs>"
    )
    _xml, results = cpacs_adapter.run_adapter(
        cpacs, step_path=str(step), output_dir=str(tmp_path / "out")
    )
    assert results["error"]["type"] == "mesh_generation_failed"
    assert "surface_density=30" in results["error"]["message"]
    assert "Illegal hash-position" in results["error"]["message"]
    assert results["converged"] is False
    assert "CL" not in results


def test_real_gmsh_meshes_in_a_child(monkeypatch, tmp_path, caplog):
    """The production path: real gmsh, in another process than this one."""
    step = tmp_path / "box.step"
    _box_step(step)

    def not_here(*_a, **_k):
        raise AssertionError("the mesher ran in the server process")

    # The child imports its own copy of the module, so this only guards
    # the process the test (the server) runs in.
    monkeypatch.setattr(cpacs_adapter, "_mesh_step_in_this_process", not_here)
    out = tmp_path / "box.su2"
    cpacs_adapter._LAST_MESH_FAILURE.clear()
    with caplog.at_level("INFO", logger="su2_mcp.cpacs_adapter"):
        ok = cpacs_adapter._mesh_step_with_gmsh(
            str(step), str(out), {"surface_density": 30, "surface_size_m": 0.5}
        )
    assert ok, cpacs_adapter._LAST_MESH_FAILURE
    text = out.read_text()
    assert text.startswith("NDIME= 3")
    assert "MARKER_TAG= WALL" in text and "MARKER_TAG= FARFIELD" in text
    # the child's log records arrive in this process's log
    assert any("Imported: 1 volumes" in r.getMessage() for r in caplog.records)


def test_a_mesher_exception_reaches_the_caller(tmp_path):
    """gmsh raising (an unreadable STEP) is an exception here too, not a crash."""
    pytest.importorskip("gmsh")
    step = tmp_path / "broken.step"
    step.write_bytes(STEP + b"not a step body\n")
    with pytest.raises(RuntimeError):
        cpacs_adapter._mesh_step_with_gmsh(str(step), str(tmp_path / "out.su2"))
    assert cpacs_adapter._LAST_MESH_FAILURE.get("type") != "mesh_generation_failed"


def test_missing_gmsh_module_is_an_import_error(monkeypatch, tmp_path):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "gmsh" else real(name, *a),
    )
    with pytest.raises(ImportError, match="gmsh"):
        cpacs_adapter._mesh_step_with_gmsh("x.step", str(tmp_path / "out.su2"))


def test_the_real_child_exits_cleanly(tmp_path):
    """The child's own exit status is 0 after a mesh, every time: a parent
    watcher that waited inside sys.stdin made Python abort at exit on some
    runs (seen 2026-11-23 while this was being written)."""
    step = tmp_path / "box.step"
    _box_step(step)
    for i in range(3):
        out, result = tmp_path / f"m{i}.su2", tmp_path / f"r{i}.json"
        cmd = mesh_child._child_command(
            str(step), str(out), '{"surface_size_m": 0.5}', str(result)
        )
        log = tmp_path / f"log{i}.txt"
        with log.open("wb") as sink:
            # standard input stays open, as the server holds it while it waits
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=sink, stderr=sink
            )
            try:
                assert proc.wait(timeout=120) == 0, log.read_text()[-800:]
            finally:
                proc.kill()
                assert proc.stdin is not None
                proc.stdin.close()
        assert "Fatal Python error" not in log.read_text()
        assert '"ok": true' in result.read_text()


def test_the_child_ends_when_the_server_goes():
    """A stopped server must not leave a mesher running on its own."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; from su2_mcp.mesh_child import _exit_when_parent_goes; "
            "_exit_when_parent_goes(); print('up', flush=True); time.sleep(60)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": SRC},
    )
    try:
        assert proc.stdout is not None and proc.stdin is not None
        assert proc.stdout.readline().strip() == b"up"
        proc.stdin.close()  # what the child sees when its parent is gone
        assert proc.wait(timeout=20) == 70
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
