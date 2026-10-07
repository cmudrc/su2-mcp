"""The CFD adapter refuses a geometry the geometry stage marked as faulty.

Added 2026-10-07 with tigl-mcp's geometry check. A wing on one side only or a
detached wing meshes and solves without complaint and returns plausible
coefficients; the refusal has to happen before meshing, from the findings
tigl-mcp wrote into the shared file.
"""

from __future__ import annotations

from pathlib import Path

from su2_mcp.cpacs_adapter import geometry_faults_from_cpacs, run_adapter

_FAULT_XML = (
    "<?xml version='1.0'?>"
    "<cpacs><vehicles><aircraft><model>"
    "<reference><area>122.4</area><length>4.2</length></reference>"
    "<analysisResults><tigl><geometryChecks checked='true'>"
    "<finding><type>wing_detached</type><severity>fault</severity>"
    "<component>D150_wing_1ID</component>"
    "<message>Wing does not touch any fuselage: 2.179 m.</message></finding>"
    "</geometryChecks></tigl></analysisResults>"
    "</model></aircraft></vehicles></cpacs>"
)
_CLEAN_XML = _FAULT_XML.replace(
    "<severity>fault</severity>", "<severity>info</severity>"
)


def test_faults_are_read_from_the_file():
    faults = geometry_faults_from_cpacs(_FAULT_XML)
    assert [f["type"] for f in faults] == ["wing_detached"]
    assert geometry_faults_from_cpacs(_CLEAN_XML) == []
    assert geometry_faults_from_cpacs("not xml") == []


def test_run_adapter_refuses_a_faulty_geometry_before_meshing(tmp_path: Path):
    xml, results = run_adapter(_FAULT_XML, output_dir=str(tmp_path), preset="laptop")
    assert results["success"] is False
    assert results["error"]["type"] == "geometry_fault"
    assert results["error"]["findings"][0]["component"] == "D150_wing_1ID"
    assert xml == _FAULT_XML  # nothing written
    assert not any(tmp_path.iterdir())  # nothing meshed


def test_override_runs_past_the_findings(tmp_path: Path):
    # With no geometry supplied the next refusal is missing_input, which shows
    # the geometry gate was passed.
    _, results = run_adapter(
        _FAULT_XML,
        output_dir=str(tmp_path),
        preset="laptop",
        ignore_geometry_findings=True,
    )
    assert results["error"]["type"] == "missing_input"


def test_files_without_checks_are_unaffected(tmp_path: Path):
    _, results = run_adapter(_CLEAN_XML, output_dir=str(tmp_path), preset="laptop")
    assert results["error"]["type"] == "missing_input"
