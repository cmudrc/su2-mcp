"""Parallel launch support for SU2.

The measured 6--8 hour fine-mesh runs in this project came from a serial
SU2_CFD using one core. This module builds the command line for a parallel
launch when, and only when, a parallel launch is actually possible:

* ``mpirun`` (or ``mpiexec``) must be on PATH, and
* the SU2 binary must be MPI-capable: either a binary named ``SU2_CFD_MPI``
  is present, or the chosen binary links against an MPI library (checked
  with otool/ldd, since running N copies of a serial binary silently
  computes the same case N times).

Rank count comes from the ``SU2_MPI_RANKS`` environment variable: unset or
``0`` means auto (all physical cores), ``1`` forces serial, any other
integer is used as given. The decision taken is reported in the run
metadata, never guessed at afterwards.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any

__all__ = ["build_solver_command", "parallel_decision"]


def _mpi_launcher() -> str | None:
    for name in ("mpirun", "mpiexec"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def _links_against_mpi(binary_path: str) -> bool:
    """True when the binary dynamically links an MPI library."""
    tool = ["otool", "-L"] if platform.system() == "Darwin" else ["ldd"]
    if shutil.which(tool[0]) is None:
        return False
    try:
        out = subprocess.run(
            [*tool, binary_path], capture_output=True, text=True, timeout=20
        ).stdout.lower()
    except Exception:
        return False
    return "libmpi" in out or "libpmpi" in out


def _requested_ranks() -> int:
    raw = os.environ.get("SU2_MPI_RANKS", "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def parallel_decision(solver: str) -> dict[str, Any]:
    """Decide how the given solver name should be launched.

    Returns a dict with: command (list of argv prefix including the solver
    executable), ranks, mode ('mpi' or 'serial'), and reason (why this mode).
    """
    requested = _requested_ranks()
    exe = shutil.which(solver)
    if exe is None:
        return {
            "command": [solver],
            "ranks": 1,
            "mode": "serial",
            "reason": f"{solver} not found on PATH; left for the caller's error path",
        }

    if requested == 1:
        return {
            "command": [exe],
            "ranks": 1,
            "mode": "serial",
            "reason": "SU2_MPI_RANKS=1 forces serial",
        }

    launcher = _mpi_launcher()
    if launcher is None:
        return {
            "command": [exe],
            "ranks": 1,
            "mode": "serial",
            "reason": "no mpirun/mpiexec on PATH",
        }

    mpi_exe = None
    sibling = shutil.which(solver + "_MPI")
    if sibling:
        mpi_exe = sibling
    elif _links_against_mpi(exe):
        mpi_exe = exe
    if mpi_exe is None:
        return {
            "command": [exe],
            "ranks": 1,
            "mode": "serial",
            "reason": (
                "binary is not MPI-capable (no *_MPI sibling and no MPI "
                "library linked); running N copies of a serial solver would "
                "repeat the same case N times"
            ),
        }

    ranks = requested or (os.cpu_count() or 1)
    return {
        "command": [launcher, "-np", str(ranks), mpi_exe],
        "ranks": ranks,
        "mode": "mpi",
        "reason": f"{os.path.basename(mpi_exe)} via {os.path.basename(launcher)}",
    }
