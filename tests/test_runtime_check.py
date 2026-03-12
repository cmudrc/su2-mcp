"""Coverage for su2_mcp.runtime_check diagnostics module."""

from __future__ import annotations

from su2_mcp.runtime_check import check_full_runtime, print_runtime_report


def test_check_full_runtime_returns_expected_keys() -> None:
    """The diagnostic dict always reports python and platform."""
    report = check_full_runtime()

    assert "python" in report
    assert "platform" in report
    assert "all_ok" in report
    assert isinstance(report["all_ok"], bool)


def test_print_runtime_report_runs_without_error(
    capsys: object,
) -> None:
    """print_runtime_report writes to stdout without raising."""
    print_runtime_report()
