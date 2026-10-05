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


def _physical_cores() -> int:
    """Physical core count. Open MPI's default slot count is physical cores,
    so asking for one rank per hardware thread (os.cpu_count) fails with
    "not enough slots" on hyperthreaded machines (seen 2026-10-05 on the lab
    server: 12 cores, 24 threads)."""
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if out.isdigit():
                return int(out)
        elif shutil.which("lscpu"):
            out = subprocess.run(
                ["lscpu", "-p=CORE,SOCKET"], capture_output=True, text=True, timeout=5
            ).stdout
            cores = {ln for ln in out.splitlines() if ln and not ln.startswith("#")}
            if cores:
                return len(cores)
    except Exception:
        pass
    return os.cpu_count() or 1


def _extra_launcher_args() -> list[str]:
    raw = os.environ.get("SU2_MPIRUN_ARGS", "").strip()
    return raw.split() if raw else []


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

    launcher = _mpi_launcher()
    mpi_exe = None
    sibling = shutil.which(solver + "_MPI")
    if sibling:
        mpi_exe = sibling
    elif _links_against_mpi(exe):
        mpi_exe = exe

    if mpi_exe is None:
        reason = (
            "SU2_MPI_RANKS=1 forces serial"
            if requested == 1
            else "no mpirun/mpiexec on PATH"
            if launcher is None
            else (
                "binary is not MPI-capable (no *_MPI sibling and no MPI "
                "library linked); running N copies of a serial solver would "
                "repeat the same case N times"
            )
        )
        return {"command": [exe], "ranks": 1, "mode": "serial", "reason": reason}

    if launcher is None:
        # An MPI-linked binary started without a launcher runs as an MPI
        # "singleton", which some Open MPI builds reject at start-up.
        return {
            "command": [mpi_exe],
            "ranks": 1,
            "mode": "serial",
            "reason": "MPI-linked binary but no mpirun/mpiexec on PATH; started as a singleton",
        }

    # An MPI build is ALWAYS started through the launcher, even for one rank:
    # Open MPI 4.1 singletons fail in MPI_Win_create (seen 2026-10-05).
    ranks = 1 if requested == 1 else (requested or _physical_cores())
    return {
        "command": [launcher, *_extra_launcher_args(), "-np", str(ranks), mpi_exe],
        "ranks": ranks,
        "mode": "mpi" if ranks > 1 else "mpi_single_rank",
        "reason": f"{os.path.basename(mpi_exe)} via {os.path.basename(launcher)}",
    }
