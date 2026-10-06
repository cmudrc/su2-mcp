"""The CFD result says it is inviscid and what CDi is.

Dry run, 2026-10-05: asked for "a RANS analysis ... and the skin-friction
drag", the agent called the Euler run RANS and reported CDi as skin friction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_aspect_ratio import _cpacs
from test_wetted_area import _cube_mesh

from su2_mcp import cpacs_adapter
from su2_mcp.cpacs_adapter import run_adapter


def test_flow_model_is_stated_even_when_the_run_is_refused(tmp_path: Path) -> None:
    _xml, results = run_adapter(_cpacs(), output_dir=str(tmp_path))
    assert results["error"]["type"] == "missing_input"
    assert results["flow_model"].startswith("Euler (inviscid)")
    assert "cannot run RANS" in results["flow_model"]


def test_drag_split_says_cdi_is_induced_not_friction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only SU2_CFD and its history are replaced; the split is the real code path."""
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
        cpacs_adapter, "_parse_history", lambda history_file: {"CL": 0.5, "CD": 0.03}
    )
    _xml, results = run_adapter(
        _cpacs(),
        flight_conditions={"mach": 0.78, "aoa": 2.0, "altitude_ft": 35000.0},
        mesh_path=str(mesh),
        output_dir=str(tmp_path / "out"),
    )
    assert results["polar_method"] == "single_point_oswald_split"
    assert "induced drag" in results["drag_split_note"]
    assert "Neither is skin friction" in results["drag_split_note"]
    assert results["CDi"] + results["CD0"] == pytest.approx(0.03, abs=1e-6)
