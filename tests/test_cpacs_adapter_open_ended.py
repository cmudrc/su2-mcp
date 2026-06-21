"""Tests for the additive open-ended SU2 mesh refinement options.

Covers:
- ``surface_density`` / ``farfield_factor`` overrides in ``run_adapter`` are
  honoured and surface in the results dict.
- Invalid overrides raise ``ValueError``.
- ``_count_su2_mesh_elements`` parses real ASCII SU2 mesh headers.
- ``_detect_cauchy_triggered`` flags the SU2 Cauchy banner.

These tests do **not** require SU2_CFD to be installed: they exercise the
adapter's input-validation + reporting paths and the small helpers, with
the SU2 call exiting via the ``missing_input`` branch when no geometry is
provided. The real solver path is covered elsewhere by the OVS smoke
tests when SU2 is available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from su2_mcp.cpacs_adapter import (
    MESH_PRESETS,
    _count_su2_mesh_elements,
    _detect_cauchy_triggered,
    run_adapter,
)

_MIN_CPACS = (
    "<?xml version='1.0'?>"
    "<cpacs><vehicles><aircraft><model>"
    "<reference><area>122.4</area><length>4.2</length></reference>"
    "</model></aircraft></vehicles></cpacs>"
)


def test_surface_density_override_recorded_in_results(tmp_path: Path) -> None:
    """Custom density should be reflected in the returned summary."""
    _xml, results = run_adapter(
        _MIN_CPACS,
        output_dir=str(tmp_path),
        preset="laptop",
        surface_density=137,
        farfield_factor=12.5,
    )
    # No geometry provided -> early missing_input error, but the requested
    # density still has to be reported so the convergence harness can log
    # the rung that was attempted.
    assert results["requested_surface_density"] == 137
    assert results["requested_farfield_factor"] == 12.5
    assert results["error"]["type"] == "missing_input"


def test_preset_path_unchanged_when_no_override(tmp_path: Path) -> None:
    """Without overrides, ``run_adapter`` still resolves to preset values."""
    _xml, results = run_adapter(
        _MIN_CPACS,
        output_dir=str(tmp_path),
        preset="workstation",
    )
    assert results["requested_surface_density"] == MESH_PRESETS["workstation"][
        "surface_density"
    ]
    assert results["requested_farfield_factor"] == MESH_PRESETS["workstation"][
        "farfield_factor"
    ]


def test_invalid_surface_density_rejected() -> None:
    with pytest.raises(ValueError):
        run_adapter(_MIN_CPACS, surface_density=0)
    with pytest.raises(ValueError):
        run_adapter(_MIN_CPACS, surface_density=-5)


def test_invalid_farfield_factor_rejected() -> None:
    with pytest.raises(ValueError):
        run_adapter(_MIN_CPACS, farfield_factor=0.0)
    with pytest.raises(ValueError):
        run_adapter(_MIN_CPACS, farfield_factor=-1.0)


def test_count_su2_mesh_elements_parses_header(tmp_path: Path) -> None:
    mesh = tmp_path / "mini.su2"
    mesh.write_text("NDIME= 3\nNELEM= 2345\nNPOIN= 678\n", encoding="utf-8")
    assert _count_su2_mesh_elements(mesh) == 2345


def test_count_su2_mesh_elements_missing_file(tmp_path: Path) -> None:
    assert _count_su2_mesh_elements(tmp_path / "nope.su2") is None


def test_detect_cauchy_triggered_recognises_banner() -> None:
    log = "Iter   100 ...\nCAUCHY CRITERIA SATISFIED on LIFT.\n+ exit"
    assert _detect_cauchy_triggered(log, Path("/nonexistent/history.csv")) is True


def test_detect_cauchy_triggered_default_false() -> None:
    assert (
        _detect_cauchy_triggered("Iter 250 ... done.", Path("/no/history.csv"))
        is False
    )
