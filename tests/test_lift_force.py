"""Dimensional lift is a tool output, not planner arithmetic.

RQ3 (2026-09-21): asked for a lift force, which no tool returned, the planner
computed one from CL with sea-level density at 35,000 ft. The adapter now
dimensionalises its own coefficients with the ISA dynamic pressure at the
stated flight condition and the file's reference area, and says so.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from su2_mcp import cpacs_adapter
from su2_mcp.cpacs_adapter import _isa_dynamic_pressure_pa, run_adapter
from test_wetted_area import _cube_mesh


def test_isa_dynamic_pressure_sea_level_and_cruise() -> None:
    # Sea level, Mach 0.3: rho 1.225, a 340.29 m/s -> q = 0.5*1.225*(102.09)^2
    assert _isa_dynamic_pressure_pa(0.0, 0.3) == pytest.approx(6383.0, rel=2e-3)
    # 35,000 ft, Mach 0.78: T 218.81 K, p 23,842 Pa, rho 0.3796, a 296.5 m/s
    assert _isa_dynamic_pressure_pa(35000.0, 0.78) == pytest.approx(10155.0, rel=3e-3)
    # Stratosphere branch is continuous with the troposphere at 11 km
    assert _isa_dynamic_pressure_pa(36089.0, 0.78) == pytest.approx(
        _isa_dynamic_pressure_pa(36090.0, 0.78), rel=1e-3
    )


def test_run_adapter_reports_lift_force_with_its_basis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only SU2_CFD is replaced; the dimensionalisation is the real code path."""
    mesh = tmp_path / "cube.su2"
    mesh.write_text(_cube_mesh())
    monkeypatch.setattr(
        cpacs_adapter,
        "_run_su2_cfd",
        lambda workdir, config_name, timeout=600: {"runtime_seconds": 0.1, "log_tail": ""},
    )
    monkeypatch.setattr(
        cpacs_adapter, "_parse_history", lambda history_file: {"CL": 0.178, "CD": 0.74}
    )
    cpacs = (
        "<?xml version='1.0'?><cpacs><vehicles><aircraft><model>"
        "<reference><area>1.0</area><length>1.0</length></reference>"
        "</model></aircraft></vehicles></cpacs>"
    )
    xml, results = run_adapter(
        cpacs,
        flight_conditions={"mach": 0.78, "aoa": 2.0, "altitude_ft": 35000.0},
        mesh_path=str(mesh),
        output_dir=str(tmp_path / "out"),
    )
    q = _isa_dynamic_pressure_pa(35000.0, 0.78)
    assert results["dynamic_pressure_pa"] == pytest.approx(q, rel=1e-3)
    assert results["lift_force_N"] == pytest.approx(0.178 * q, rel=1e-3)
    assert results["drag_force_N"] == pytest.approx(0.74 * q, rel=1e-3)
    assert "ISA dynamic pressure" in results["force_basis"]
    # The sea-level value the planner used (3133 N) is not what the tool says.
    assert results["lift_force_N"] < 2000
    aero = ET.fromstring(xml).find(".//analysisResults/aero")
    assert aero is not None
    assert float(aero.findtext("liftForceN")) == pytest.approx(0.178 * q, rel=1e-3)
    assert aero.findtext("forceBasis") == results["force_basis"]


def test_no_force_when_coefficients_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mesh = tmp_path / "cube.su2"
    mesh.write_text(_cube_mesh())
    monkeypatch.setattr(
        cpacs_adapter,
        "_run_su2_cfd",
        lambda workdir, config_name, timeout=600: {"runtime_seconds": 0.1, "log_tail": ""},
    )
    monkeypatch.setattr(
        cpacs_adapter, "_parse_history", lambda history_file: {"CL": None, "CD": None}
    )
    cpacs = (
        "<cpacs><vehicles><aircraft><model>"
        "<reference><area>1.0</area><length>1.0</length></reference>"
        "</model></aircraft></vehicles></cpacs>"
    )
    xml, results = run_adapter(cpacs, mesh_path=str(mesh), output_dir=str(tmp_path / "o"))
    assert "lift_force_N" not in results
    assert ET.fromstring(xml).find(".//aero/liftForceN") is None
