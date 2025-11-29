"""Helpers for invoking SU2 binaries safely."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

from su2_mcp_server.session_manager import LastRunMetadata


class SU2Runner:
    """Run SU2 commands with subprocess while capturing metadata."""

    def __init__(self, workdir: Path) -> None:
        """Create a runner bound to a specific working directory."""
        self.workdir = workdir

    def run(
        self,
        solver: str,
        config_path: Path,
        max_runtime_seconds: int,
        capture_log_lines: int,
    ) -> dict[str, object]:
        """Execute a SU2 solver and return structured metadata."""
        start = time.time()
        try:
            process = subprocess.run(
                [solver, str(config_path)],
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=max_runtime_seconds,
                check=False,
                text=True,
            )
            output_text = process.stdout or ""
            runtime = time.time() - start
            tail_lines = "\n".join(output_text.splitlines()[-capture_log_lines:])
            residual_history = self._parse_history_files()
            return {
                "success": process.returncode == 0,
                "solver": solver,
                "config_used": str(config_path),
                "exit_code": int(process.returncode),
                "runtime_seconds": runtime,
                "log_tail": tail_lines,
                "residual_history": residual_history,
            }
        except subprocess.TimeoutExpired as exc:
            runtime = time.time() - start
            return {
                "success": False,
                "solver": solver,
                "config_used": str(config_path),
                "exit_code": -1,
                "runtime_seconds": runtime,
                "log_tail": "Process timed out",
                "residual_history": None,
                "error": {
                    "type": "timeout",
                    "message": "SU2 solver execution timed out",
                    "details": str(exc),
                },
            }
        except FileNotFoundError as exc:
            runtime = time.time() - start
            return {
                "success": False,
                "solver": solver,
                "config_used": str(config_path),
                "exit_code": -1,
                "runtime_seconds": runtime,
                "log_tail": "",
                "residual_history": None,
                "error": {
                    "type": "missing_binary",
                    "message": f"Solver binary '{solver}' not found",
                    "details": str(exc),
                },
            }

    def _parse_history_files(self) -> list[dict[str, object]] | None:
        for candidate in (self.workdir / "history.csv", self.workdir / "history.dat"):
            if candidate.exists():
                return self._read_history(candidate)
        return None

    def _read_history(self, path: Path) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                header = handle.readline().strip().split(",")
                for line in handle:
                    values = [value.strip() for value in line.split(",")]
                    if len(values) != len(header):
                        continue
                    entry: dict[str, object] = {}
                    for key, value in zip(header, values, strict=False):
                        try:
                            entry[key] = float(value)
                        except ValueError:
                            entry[key] = value
                    rows.append(entry)
        except FileNotFoundError:
            return []
        return rows


def build_last_run_metadata(result: Mapping[str, object]) -> LastRunMetadata:
    """Convert a solver result payload into `LastRunMetadata`."""

    exit_code_raw = result.get("exit_code", -1)
    runtime_raw = result.get("runtime_seconds", 0.0)

    exit_code = int(exit_code_raw) if isinstance(exit_code_raw, (int, float, str)) else -1
    runtime_seconds = (
        float(runtime_raw) if isinstance(runtime_raw, (int, float, str)) else 0.0
    )

    return LastRunMetadata(
        solver=str(result.get("solver", "")),
        config_used=str(result.get("config_used", "")),
        exit_code=exit_code,
        runtime_seconds=runtime_seconds,
        log_tail=str(result.get("log_tail", "")),
    )
