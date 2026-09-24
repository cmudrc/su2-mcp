"""A meaningless flight condition is refused before anything runs.

2026-09-23: asked to run with the Mach number omitted, the planner passed
mach=0. SU2 ran and returned coefficients of order 1e-11 without failing.
"""

from __future__ import annotations

import pytest

from su2_mcp.cpacs_adapter import run_adapter

CPACS = (
    "<cpacs><vehicles><aircraft><model>"
    "<reference><area>1.0</area><length>1.0</length></reference>"
    "</model></aircraft></vehicles></cpacs>"
)


@pytest.mark.parametrize(
    "fc,param",
    [
        ({"mach": 0.0, "aoa": 2.0, "altitude_ft": 35000.0}, "mach"),
        ({"mach": 4.0, "aoa": 2.0, "altitude_ft": 35000.0}, "mach"),
        ({"mach": 0.78, "aoa": 45.0, "altitude_ft": 35000.0}, "aoa"),
        ({"mach": 0.78, "aoa": 2.0, "altitude_ft": 250000.0}, "altitude_ft"),
    ],
)
def test_out_of_range_condition_is_a_structured_error(tmp_path, fc, param):
    xml, res = run_adapter(CPACS, flight_conditions=fc, mesh_path="nonexistent.su2",
                           output_dir=str(tmp_path))
    assert res["success"] is False
    assert res["error"]["type"] == "invalid_input"
    assert res["error"]["parameter"] == param
    assert xml == CPACS  # nothing written
    assert not any(tmp_path.iterdir())  # nothing run


def test_in_range_condition_reaches_the_geometry_check(tmp_path):
    _, res = run_adapter(CPACS, flight_conditions={"mach": 0.78, "aoa": 2.0, "altitude_ft": 35000.0},
                         output_dir=str(tmp_path))
    # No mesh and no STEP supplied: the next real check fires, not the range check.
    assert res["error"]["type"] == "missing_input"
