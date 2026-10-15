"""A reference sweep round-trips through the CPACS file, its fits are the
least-squares fits of its own points, and lookups never extrapolate."""

import xml.etree.ElementTree as ET

import pytest

from su2_mcp import aero_sweep as s

CPACS = """<?xml version="1.0"?>
<cpacs><header><name>t</name><version>1</version><cpacsVersion>3.2</cpacsVersion></header>
<vehicles><aircraft><model uID="m"><name>test</name><reference><area>122.4</area><length>4.2</length></reference>
<analysisResults><aero><solver>su2_cfd</solver><mach>0.78</mach><aoaDeg>2.0</aoaDeg>
<coefficients><CL>0.0742</CL><CD>0.0213</CD><CD0>0.0211</CD0></coefficients></aero></analysisResults>
</model></aircraft></vehicles></cpacs>"""


def _runs():
    # CL = 0.1 + 0.09 a, CD = 0.02 + 0.045 CL^2, exactly, so the fits are known
    out = []
    for a in (-2, 0, 2, 4, 6, 8, 10):
        cl = 0.1 + 0.09 * a
        out.append(
            {
                "aoa_deg": float(a),
                "CL": cl,
                "CD": 0.02 + 0.045 * cl * cl,
                "L_over_D": cl / (0.02 + 0.045 * cl * cl),
                "cauchy_triggered": True,
                "iterations": 150,
                "runtime_seconds": 600.0,
                "error": None,
            }
        )
    out.append(
        {"aoa_deg": 12.0, "error": {"type": "solver_failure", "message": "diverged"}}
    )
    return out


def _meta():
    return {
        "solver": "su2_cfd 8.4.0",
        "flow_model": "Euler (inviscid)",
        "mesh_rule": "40 cells across the reference chord",
        "mesh_cells": 1043902,
        "mesh_wall_faces": 60000,
        "surface_size_m": 0.105,
        "mach": 0.78,
        "altitude_ft": 35000.0,
        "reference_area_m2": 122.4,
        "machine": "drc-lab, serial SU2",
        "source": "lab_server/07_run_aoa_sweep.py",
        "note": "test",
    }


def test_build_fits_recover_the_generating_law():
    sw = s.build_sweep("ref_chord40", "reference", _runs(), _meta())
    assert len(sw["points"]) == 7 and sw["excluded"][0]["aoa_deg"] == 12.0
    pol, lc = sw["fit"]["polar"], sw["fit"]["lift_curve"]
    assert pol["CD0"] == pytest.approx(0.02, abs=1e-9) and pol["k"] == pytest.approx(
        0.045, abs=1e-9
    )
    assert pol["n_points"] == 6  # aoa <= 8 only
    assert lc["CL0"] == pytest.approx(0.1, abs=1e-9) and lc[
        "CL_alpha_per_deg"
    ] == pytest.approx(0.09, abs=1e-9)
    assert pol["r_squared"] == pytest.approx(1.0) and lc["r_squared"] == pytest.approx(
        1.0
    )


def test_round_trip_keeps_the_single_point_aero_node_and_adds_a_header_line():
    sw = s.build_sweep("ref_chord40", "reference", _runs(), _meta())
    xml = s.write_sweep_to_cpacs(CPACS, sw)
    root = ET.fromstring(xml)
    assert root.findtext(".//analysisResults/aero/coefficients/CL") == "0.0742"
    back = s.read_sweeps(xml)
    assert (
        len(back) == 1
        and back[0]["uid"] == "ref_chord40"
        and back[0]["label"] == "reference"
    )
    assert [p["aoa_deg"] for p in back[0]["points"]] == [-2, 0, 2, 4, 6, 8, 10]
    assert back[0]["fit"]["polar"]["k"] == pytest.approx(0.045, abs=1e-9)
    assert (
        back[0]["mesh_cells"] == 1043902
        and back[0]["points"][0]["cauchy_triggered"] is True
    )
    mods = [u.findtext("modification") for u in root.findall("header/updates/update")]
    assert any("aeroSweep/ref_chord40 (7 Euler runs" in m for m in mods)
    # writing the same uID again replaces, does not duplicate
    xml2 = s.write_sweep_to_cpacs(xml, sw)
    assert len(s.read_sweeps(xml2)) == 1


def test_lookup_is_exact_on_a_run_interpolated_between_runs_and_refuses_outside():
    sw = s.build_sweep("ref_chord40", "reference", _runs(), _meta())
    exact = s.lookup(sw, at_aoa_deg=4.0)["at_aoa_deg"]
    assert exact["basis"] == "exact" and exact["CL"] == pytest.approx(0.46)
    mid = s.lookup(sw, at_aoa_deg=3.0)["at_aoa_deg"]
    assert (
        "between two stored runs" in mid["basis"]
        and mid["CL"] == pytest.approx(0.37)
        and len(mid["derived_from"]) == 2
    )
    inv = s.lookup(sw, at_cl=0.572)["at_cl"]
    assert inv["aoa_deg"] == pytest.approx((0.572 - 0.1) / 0.09, abs=1e-9)
    assert inv["CD"] == pytest.approx(
        0.02 + 0.045 * 0.572**2, abs=5e-4
    )  # linear in CL between the runs at 4 and 6 deg
    out = s.lookup(sw, at_aoa_deg=15.0)["at_aoa_deg"]
    assert out["error"]["type"] == "outside_stored_range"
    assert s.lookup(sw, at_cl=5.0)["at_cl"]["error"]["type"] == "outside_stored_range"


def test_file_without_sweeps_reads_empty():
    assert s.read_sweeps(CPACS) == []
