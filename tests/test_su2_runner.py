"""Unit tests for SU2 process runner helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from su2_mcp.su2_runner import SU2Runner, build_last_run_metadata


def test_run_success_parses_history_and_log_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Successful runs should include history parsing and trailing log lines."""
    history = tmp_path / "history.csv"
    history.write_text("iter,residual\n1,0.1\n2,0.01\n", encoding="utf-8")

    def _fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="line1\nline2\nline3\n")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = SU2Runner(tmp_path)
    result = runner.run("SU2_CFD", tmp_path / "config.cfg", 10, 2)

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["log_tail"] == "line2\nline3"
    assert result["residual_history"] == [
        {"iter": 1.0, "residual": 0.1},
        {"iter": 2.0, "residual": 0.01},
    ]


def test_run_timeout_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Timeouts should map to a stable error payload."""

    def _fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(cmd=["SU2_CFD"], timeout=10)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = SU2Runner(tmp_path)
    result = runner.run("SU2_CFD", tmp_path / "config.cfg", 10, 2)

    assert result["success"] is False
    assert result["error"]["type"] == "timeout"
    assert result["log_tail"] == "Process timed out"


def test_run_missing_binary_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing solver binaries should return missing_binary details."""

    def _fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise FileNotFoundError("missing")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner = SU2Runner(tmp_path)
    result = runner.run("MISSING", tmp_path / "config.cfg", 10, 2)

    assert result["success"] is False
    assert result["error"]["type"] == "missing_binary"
    assert "MISSING" in result["error"]["message"]


def test_read_history_skips_malformed_rows(tmp_path: Path) -> None:
    """History parsing should skip rows that do not match the header width."""
    history = tmp_path / "history.dat"
    history.write_text("iter,residual\n1,0.1\ninvalid\n2,done\n", encoding="utf-8")

    runner = SU2Runner(tmp_path)
    parsed = runner._parse_history_files()

    assert parsed == [
        {"iter": 1.0, "residual": 0.1},
        {"iter": 2.0, "residual": "done"},
    ]


def test_read_history_missing_file_returns_empty_list(tmp_path: Path) -> None:
    """Direct history reads on missing files should return an empty list."""
    runner = SU2Runner(tmp_path)
    assert runner._read_history(tmp_path / "absent.csv") == []


def test_build_last_run_metadata_coerces_types() -> None:
    """Metadata builder should coerce numeric-like values and default invalid ones."""
    metadata = build_last_run_metadata(
        {
            "solver": "SU2_CFD",
            "config_used": "cfg.cfg",
            "exit_code": "2",
            "runtime_seconds": "1.5",
            "log_tail": "tail",
        }
    )
    assert metadata.exit_code == 2
    assert metadata.runtime_seconds == pytest.approx(1.5)

    fallback = build_last_run_metadata(
        {"exit_code": object(), "runtime_seconds": object()}
    )
    assert fallback.exit_code == -1
    assert fallback.runtime_seconds == 0.0
