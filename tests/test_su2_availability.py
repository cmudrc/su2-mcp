"""Tests for SU2 availability helpers."""

from __future__ import annotations

import pytest

from su2_mcp import su2_availability


def test_check_su2_installation_reports_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing binaries should report installed=False and missing names."""
    monkeypatch.setattr(
        su2_availability,
        "discover_su2_binaries",
        lambda candidates=None: [su2_availability.SU2BinaryStatus("SU2_CFD", None)],
    )

    summary = su2_availability.check_su2_installation()

    assert summary["installed"] is False
    assert summary["missing"] == ["SU2_CFD"]


def test_summarize_binaries_reports_presence() -> None:
    """Summaries should mark installed=True when any binary is available."""
    statuses = [
        su2_availability.SU2BinaryStatus("SU2_CFD", "/usr/bin/SU2_CFD"),
        su2_availability.SU2BinaryStatus("SU2_DEF", None),
    ]

    summary = su2_availability.summarize_binaries(statuses)

    assert summary["installed"] is True
    assert summary["missing"] == ["SU2_DEF"]
