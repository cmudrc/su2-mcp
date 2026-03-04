"""Deterministic example smoke tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.examples_smoke


def _run_example(relative_path: str) -> subprocess.CompletedProcess[str]:
    """Execute an example script from the repository root."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, relative_path],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_tool_discovery_example_runs() -> None:
    """Tool discovery returns a deterministic list containing core SU2 tools."""
    completed = _run_example("examples/client/tool_discovery.py")
    assert completed.returncode == 0, completed.stderr

    payload = json.loads(completed.stdout)
    assert payload["tool_count"] >= 12
    assert "create_su2_session" in payload["tool_names"]
    assert "run_su2_solver" in payload["tool_names"]


def test_session_lifecycle_example_runs() -> None:
    """The lifecycle example opens and closes a session successfully."""
    completed = _run_example("examples/su2/session_lifecycle.py")
    assert completed.returncode == 0, completed.stderr

    payload = json.loads(completed.stdout)
    assert payload["session_opened"] is True
    assert payload["session_closed"] is True
    assert "MESH_FILENAME" in payload["config_keys"]


def test_http_launch_config_example_runs() -> None:
    """The HTTP launch config example emits expected parser values."""
    completed = _run_example("examples/server/http_launch_config.py")
    assert completed.returncode == 0, completed.stderr

    payload = json.loads(completed.stdout)
    assert payload == {
        "host": "127.0.0.1",
        "path": "/mcp",
        "port": 8000,
        "transport": "http",
    }


@pytest.mark.examples_full
def test_results_snapshot_example_runs() -> None:
    """The results snapshot example returns stable, deterministic metadata."""
    completed = _run_example("examples/su2/results_snapshot.py")
    assert completed.returncode == 0, completed.stderr

    payload = json.loads(completed.stdout)
    assert payload["file_count"] >= 1
    assert payload["first_residual"] == 0.1
    assert payload["truncated"] is True
