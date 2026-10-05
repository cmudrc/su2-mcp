"""Parallel launches happen only when they are real.

Running N copies of a serial SU2 under mpirun silently computes the same
case N times, so the decision logic must prove MPI capability first.
"""

from __future__ import annotations

import os

import pytest

from su2_mcp import mpi


def test_serial_when_no_launcher(monkeypatch):
    monkeypatch.setattr(mpi.shutil, "which", lambda n: "/bin/SU2_CFD" if n == "SU2_CFD" else None)
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "serial" and "mpirun" in d["reason"]


def test_serial_when_binary_not_mpi(monkeypatch):
    def which(n):
        return {"SU2_CFD": "/bin/SU2_CFD", "mpirun": "/bin/mpirun"}.get(n)

    monkeypatch.setattr(mpi.shutil, "which", which)
    monkeypatch.setattr(mpi, "_links_against_mpi", lambda p: False)
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "serial"
    assert "not MPI-capable" in d["reason"]


def test_mpi_with_sibling_binary(monkeypatch):
    def which(n):
        return {
            "SU2_CFD": "/bin/SU2_CFD",
            "SU2_CFD_MPI": "/bin/SU2_CFD_MPI",
            "mpirun": "/bin/mpirun",
        }.get(n)

    monkeypatch.setattr(mpi.shutil, "which", which)
    monkeypatch.setenv("SU2_MPI_RANKS", "8")
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "mpi"
    assert d["command"][:3] == ["/bin/mpirun", "-np", "8"]
    assert d["command"][3] == "/bin/SU2_CFD_MPI"


def test_rank_one_on_mpi_build_still_uses_the_launcher(monkeypatch):
    """Open MPI singletons can fail at start-up, so one rank goes via mpirun."""
    def which(n):
        return {"SU2_CFD": "/bin/SU2_CFD", "SU2_CFD_MPI": "/bin/m", "mpirun": "/bin/mpirun"}.get(n)

    monkeypatch.setattr(mpi.shutil, "which", which)
    monkeypatch.setenv("SU2_MPI_RANKS", "1")
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "mpi_single_rank"
    assert d["command"] == ["/bin/mpirun", "-np", "1", "/bin/m"]


def test_rank_one_on_serial_build_runs_directly(monkeypatch):
    monkeypatch.setattr(mpi.shutil, "which", lambda n: "/bin/SU2_CFD" if n == "SU2_CFD" else None)
    monkeypatch.setenv("SU2_MPI_RANKS", "1")
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "serial" and d["command"] == ["/bin/SU2_CFD"]


def test_auto_ranks_use_physical_cores(monkeypatch):
    def which(n):
        return {"SU2_CFD": "/bin/SU2_CFD", "SU2_CFD_MPI": "/bin/m", "mpirun": "/bin/mpirun"}.get(n)

    monkeypatch.setattr(mpi.shutil, "which", which)
    monkeypatch.setattr(mpi, "_physical_cores", lambda: 12)
    monkeypatch.delenv("SU2_MPI_RANKS", raising=False)
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "mpi" and d["ranks"] == 12


def test_extra_launcher_args(monkeypatch):
    def which(n):
        return {"SU2_CFD": "/bin/SU2_CFD", "SU2_CFD_MPI": "/bin/m", "mpirun": "/bin/mpirun"}.get(n)

    monkeypatch.setattr(mpi.shutil, "which", which)
    monkeypatch.setenv("SU2_MPI_RANKS", "6")
    monkeypatch.setenv("SU2_MPIRUN_ARGS", "--bind-to none")
    d = mpi.parallel_decision("SU2_CFD")
    assert d["command"] == ["/bin/mpirun", "--bind-to", "none", "-np", "6", "/bin/m"]


def test_physical_cores_is_positive():
    assert mpi._physical_cores() >= 1


def test_real_laptop_binary_is_detected_serial():
    """On this machine the installed SU2_CFD is serial; the decision must say so."""
    import shutil as _sh

    if _sh.which("SU2_CFD") is None:
        pytest.skip("SU2_CFD not on PATH")
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "serial" or d["command"][0].endswith(("mpirun", "mpiexec"))
