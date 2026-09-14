"""The Gmsh mesher refuses a STEP it cannot honestly mesh, with the reason.

Two cases found 2026-09-14 in the F25 history: a STEP of loose shells with no
closed solid (the farfield box is fragmented by faces and the 'fluid' has no
aircraft cavity), and a millimetre file (TiGL's default), which would scale
every coefficient by a million against the CPACS reference area. Both must be
refused up front rather than run. These tests build the STEP files with gmsh
itself, so they need the gmsh Python module and are skipped without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from su2_mcp.cpacs_adapter import (
    _LAST_MESH_FAILURE,
    _mesh_consistency_error,
    _mesh_step_with_gmsh,
    run_adapter,
)

gmsh = pytest.importorskip("gmsh")

_CPACS = (
    "<?xml version='1.0'?><cpacs><vehicles><aircraft><model>"
    "<reference><area>1.0</area><length>1.0</length></reference>"
    "</model></aircraft></vehicles></cpacs>"
)


def _write_step(path: Path, build) -> None:
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        build()
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def test_faces_without_a_solid_are_refused(tmp_path: Path) -> None:
    step = tmp_path / "shell.step"
    # an open shell: one disk face, no volume
    _write_step(step, lambda: gmsh.model.occ.addDisk(0, 0, 0, 1.0, 1.0))
    _LAST_MESH_FAILURE.clear()
    assert _mesh_step_with_gmsh(str(step), str(tmp_path / "out.su2")) is False
    assert "no closed solids" in _LAST_MESH_FAILURE["reason"]
    assert not (tmp_path / "out.su2").exists()


def test_millimetre_geometry_is_refused(tmp_path: Path) -> None:
    step = tmp_path / "mm.step"
    _write_step(step, lambda: gmsh.model.occ.addBox(0, 0, 0, 40000.0, 4000.0, 4000.0))
    _LAST_MESH_FAILURE.clear()
    assert _mesh_step_with_gmsh(str(step), str(tmp_path / "out.su2")) is False
    assert "not in metres" in _LAST_MESH_FAILURE["reason"]


def test_run_adapter_reports_the_reason(tmp_path: Path) -> None:
    step = tmp_path / "shell.step"
    _write_step(step, lambda: gmsh.model.occ.addDisk(0, 0, 0, 1.0, 1.0))
    _xml, results = run_adapter(
        _CPACS, step_path=str(step), output_dir=str(tmp_path / "run")
    )
    assert results["error"]["type"] == "meshing_failure"
    assert "no closed solids" in results["error"]["details"]
    assert results["converged"] is False


def test_consistency_check_accepts_the_d150_numbers() -> None:
    # coarse D150: 49,668 tets, 2,894 wall faces, 712.88 m2 against 719.24 m2 CAD
    assert _mesh_consistency_error(719.24, 712.88, 49_668, 2_894) is None


def test_consistency_check_rejects_the_f25_garbage_mesh() -> None:
    msg = _mesh_consistency_error(853.44, 23_322_077.655, 5_871, 15_342)
    assert msg is not None and "not the aircraft skin" in msg


def test_consistency_check_rejects_an_unfilled_domain() -> None:
    msg = _mesh_consistency_error(853.44, 850.0, 5_871, 15_342)
    assert msg is not None and "did not fill the domain" in msg


def test_consistency_check_rejects_a_missing_wall() -> None:
    assert "no WALL marker" in (_mesh_consistency_error(700.0, None, 1000, None) or "")
