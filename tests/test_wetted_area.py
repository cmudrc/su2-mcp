"""The wetted area reported by the SU2 adapter is the summed area of the wall
faces of the mesh the run used, and nothing else.

Ron Engelbeck suggested (2026-09) summing the surface patches of the CFD mesh
for the mass-properties stage. These tests pin the arithmetic on a unit cube
(area 6), the quad path, the half-model doubling, and that no wall marker means
no number rather than a guess. The run_adapter test monkeypatches SU2_CFD only;
the mesh parsing is the real code path.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from su2_mcp import cpacs_adapter
from su2_mcp.cpacs_adapter import _su2_wall_area, run_adapter, write_to_cpacs

_CUBE_POINTS = [
    (0, 0, 0),
    (1, 0, 0),
    (1, 1, 0),
    (0, 1, 0),
    (0, 0, 1),
    (1, 0, 1),
    (1, 1, 1),
    (0, 1, 1),
]
_CUBE_QUADS = [
    (0, 1, 2, 3),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
]
_CUBE_TRIS = [t for q in _CUBE_QUADS for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]


def _cube_mesh(
    quads: bool = False, wall: str = "WALL", extra_marker: str | None = None
) -> str:
    """A minimal SU2 ASCII mesh: one tet as the 'volume', the cube skin as a marker."""
    lines = ["NDIME= 3", "NELEM= 1", "10 0 1 2 4 0", f"NPOIN= {len(_CUBE_POINTS)}"]
    lines += [f"{x} {y} {z} {i}" for i, (x, y, z) in enumerate(_CUBE_POINTS)]
    faces = _CUBE_QUADS if quads else _CUBE_TRIS
    code = 9 if quads else 5
    nmark = 2 if extra_marker else 1
    lines += [f"NMARK= {nmark}", f"MARKER_TAG= {wall}", f"MARKER_ELEMS= {len(faces)}"]
    lines += [f"{code} " + " ".join(str(i) for i in f) for f in faces]
    if extra_marker:
        lines += [f"MARKER_TAG= {extra_marker}", "MARKER_ELEMS= 1", "5 0 1 2"]
    return "\n".join(lines) + "\n"


def test_unit_cube_of_triangles_has_area_six(tmp_path: Path) -> None:
    m = tmp_path / "cube.su2"
    m.write_text(_cube_mesh())
    r = _su2_wall_area(m)
    assert r is not None
    assert r["wetted_area_m2"] == pytest.approx(6.0)
    assert r["wetted_area_wall_faces"] == 12
    assert r["wetted_area_wall_markers"] == ["WALL"]
    assert "lower bound" in r["wetted_area_source"]


def test_quadrilateral_faces_are_supported(tmp_path: Path) -> None:
    m = tmp_path / "cube_q.su2"
    m.write_text(_cube_mesh(quads=True))
    r = _su2_wall_area(m)
    assert r is not None
    assert r["wetted_area_m2"] == pytest.approx(6.0)
    assert r["wetted_area_wall_faces"] == 6


def test_symmetry_marker_means_half_model_and_doubles(tmp_path: Path) -> None:
    m = tmp_path / "half.su2"
    m.write_text(_cube_mesh(extra_marker="SYMMETRY"))
    r = _su2_wall_area(m)
    assert r is not None
    assert r["wetted_area_m2"] == pytest.approx(12.0)
    assert "doubled" in r["wetted_area_source"]


def test_no_wall_marker_gives_none_not_a_guess(tmp_path: Path) -> None:
    m = tmp_path / "nowall.su2"
    m.write_text(_cube_mesh(wall="FARFIELD"))
    assert _su2_wall_area(m) is None
    assert _su2_wall_area(tmp_path / "missing.su2") is None


def test_wetted_area_is_written_to_cpacs_with_its_source() -> None:
    xml = (
        "<cpacs><vehicles><aircraft><model><reference><area>1</area>"
        "<length>1</length></reference></model></aircraft></vehicles></cpacs>"
    )
    out = write_to_cpacs(
        xml,
        {
            "solver": "su2_cfd",
            "converged": True,
            "CL": 0.2,
            "CD": 0.01,
            "wetted_area_m2": 6.0,
            "wetted_area_source": "sum of the wall-marker faces",
            "wetted_area_wall_faces": 12,
        },
    )
    aero = ET.fromstring(out).find(".//analysisResults/aero")
    assert aero is not None
    assert aero.findtext("wettedAreaM2") == "6.0"
    assert aero.findtext("wettedAreaSource") == "sum of the wall-marker faces"
    assert aero.findtext("wettedAreaWallFaces") == "12"


def test_write_to_cpacs_omits_wetted_area_when_unknown() -> None:
    xml = "<cpacs><vehicles><aircraft><model/></aircraft></vehicles></cpacs>"
    out = write_to_cpacs(xml, {"solver": "su2_cfd", "converged": False})
    assert ET.fromstring(out).find(".//aero/wettedAreaM2") is None


def test_run_adapter_reports_wetted_area_of_the_mesh_it_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only SU2_CFD itself is replaced; mesh handling and parsing are real."""
    mesh = tmp_path / "cube.su2"
    mesh.write_text(_cube_mesh())
    monkeypatch.setattr(
        cpacs_adapter,
        "_run_su2_cfd",
        lambda workdir, config_name, timeout=600: {
            "runtime_seconds": 0.1,
            "log_tail": "",
        },
    )
    monkeypatch.setattr(
        cpacs_adapter, "_parse_history", lambda history_file: {"CL": 0.25, "CD": 0.0125}
    )
    cpacs = (
        "<?xml version='1.0'?><cpacs><vehicles><aircraft><model>"
        "<reference><area>1.0</area><length>1.0</length></reference>"
        "</model></aircraft></vehicles></cpacs>"
    )
    xml, results = run_adapter(
        cpacs, mesh_path=str(mesh), output_dir=str(tmp_path / "out")
    )
    assert results["wetted_area_m2"] == pytest.approx(6.0)
    assert results["mesh_source"] == f"existing:{mesh}"
    assert ET.fromstring(xml).findtext(".//aero/wettedAreaM2") == "6.0"


def test_run_adapter_rejects_nonpositive_surface_size(monkeypatch):
    """surface_size_m must be a positive length in metres."""
    import pytest

    from su2_mcp import cpacs_adapter as a

    with pytest.raises(ValueError, match="surface_size_m"):
        a.run_adapter("<cpacs/>", surface_size_m=0.0)


def test_surface_size_m_sets_the_near_wall_size(tmp_path):
    """A smaller absolute surface size yields more WALL faces on the same body,
    and the recorded size is the one requested (real gmsh, small box)."""
    import pytest

    gmsh = pytest.importorskip("gmsh")
    from su2_mcp import cpacs_adapter as a

    step = tmp_path / "box.step"
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.occ.addBox(0, 0, 0, 2.0, 1.0, 1.0)
        gmsh.model.occ.synchronize()
        gmsh.write(str(step))
    finally:
        gmsh.finalize()
    faces = {}
    for size in (0.5, 0.25):
        out = tmp_path / f"m_{size}.su2"
        a._LAST_MESH_FAILURE.clear()
        ok = a._mesh_step_with_gmsh(str(step), str(out),
                                    {"surface_density": 30, "farfield_factor": 10.0, "surface_size_m": size})
        assert ok, a._LAST_MESH_FAILURE
        faces[size] = a._count_su2_wall_faces(str(out))
    assert faces[0.25] > faces[0.5] > 0


def test_count_su2_wall_faces(tmp_path):
    from su2_mcp import cpacs_adapter as a

    mesh = tmp_path / "m.su2"
    mesh.write_text("NDIME= 3\nNELEM= 2\nNMARK= 2\nMARKER_TAG= FARFIELD\nMARKER_ELEMS= 7\nMARKER_TAG= WALL\nMARKER_ELEMS= 42\n")
    assert a._count_su2_wall_faces(str(mesh)) == 42
    assert a._count_su2_wall_faces(str(tmp_path / "missing.su2")) is None
