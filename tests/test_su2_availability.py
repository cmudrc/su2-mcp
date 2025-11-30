"""Tests for SU2 availability helpers."""

from __future__ import annotations

import pytest

from su2_mcp_server import su2_availability


def test_check_su2_installation_reports_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing binaries should be reported with installed set to False."""
    monkeypatch.setattr(
        su2_availability,
        "discover_su2_binaries",
        lambda candidates=None: [su2_availability.SU2BinaryStatus("SU2_CFD", None)],
    )

    summary = su2_availability.check_su2_installation()

    assert summary["installed"] is False
    assert summary["missing"] == ["SU2_CFD"]
