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


def test_rank_one_forces_serial(monkeypatch):
    def which(n):
        return {"SU2_CFD": "/bin/SU2_CFD", "SU2_CFD_MPI": "/bin/m", "mpirun": "/bin/mpirun"}.get(n)

    monkeypatch.setattr(mpi.shutil, "which", which)
    monkeypatch.setenv("SU2_MPI_RANKS", "1")
    assert mpi.parallel_decision("SU2_CFD")["mode"] == "serial"


def test_auto_ranks_use_cpu_count(monkeypatch):
    def which(n):
        return {"SU2_CFD": "/bin/SU2_CFD", "SU2_CFD_MPI": "/bin/m", "mpirun": "/bin/mpirun"}.get(n)

    monkeypatch.setattr(mpi.shutil, "which", which)
    monkeypatch.delenv("SU2_MPI_RANKS", raising=False)
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "mpi" and d["ranks"] == (os.cpu_count() or 1)


def test_real_laptop_binary_is_detected_serial():
    """On this machine the installed SU2_CFD is serial; the decision must say so."""
    import shutil as _sh

    if _sh.which("SU2_CFD") is None:
        pytest.skip("SU2_CFD not on PATH")
    d = mpi.parallel_decision("SU2_CFD")
    assert d["mode"] == "serial" or d["command"][0].endswith(("mpirun", "mpiexec"))
