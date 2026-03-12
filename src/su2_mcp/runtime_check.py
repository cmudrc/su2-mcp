"""Runtime validation for SU2 and Gmsh dependencies."""

from __future__ import annotations

import shutil
import subprocess
import sys

from su2_mcp.su2_availability import check_su2_installation

CONDA_INSTALL_CMD = "conda install -c conda-forge su2 gmsh python-gmsh"

DOWNLOAD_URL = "https://su2code.github.io/download.html"

INSTALL_GUIDE = f"""\
SU2 binaries are not available on your PATH.

To install, choose one of the following options:

  1. Conda (recommended):
     {CONDA_INSTALL_CMD}

  2. Conda environment file (ships with this repo):
     conda env create -f environment.yml
     conda activate su2-mcp

  3. Pre-built binaries from SU2 Foundation:
     {DOWNLOAD_URL}

  4. Install script (Linux/macOS):
     bash scripts/install_su2.sh
"""


def _get_binary_version(name: str) -> str | None:
    """Try to get the version string from an SU2 binary."""
    path = shutil.which(name)
    if path is None:
        return None
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stdout + result.stderr).strip()
        for line in output.splitlines():
            low = line.lower()
            if "release" in low or "version" in low or "su2" in low:
                return line.strip()
        return output.splitlines()[0] if output else "unknown"
    except Exception:
        return "installed (version unknown)"


def check_full_runtime() -> dict[str, object]:
    """Probe the environment for SU2, Gmsh, and Python dependencies."""
    results: dict[str, object] = {
        "python": sys.version,
        "platform": sys.platform,
    }

    su2_info = check_su2_installation()
    su2_cfd_version = _get_binary_version("SU2_CFD")
    results["su2"] = {
        "available": su2_info["installed"],
        "binaries": su2_info["binaries"],
        "version": su2_cfd_version,
    }

    gmsh_bin = shutil.which("gmsh")
    try:
        import gmsh as _gmsh  # type: ignore[import-untyped]  # noqa: F401

        results["gmsh"] = {
            "available": True,
            "python_api": True,
            "cli": gmsh_bin or "not on PATH",
        }
    except Exception:
        results["gmsh"] = {
            "available": gmsh_bin is not None,
            "python_api": False,
            "cli": gmsh_bin or "not on PATH",
        }

    all_ok = bool(su2_info["installed"]) and (
        isinstance(results.get("gmsh"), dict)
        and results["gmsh"].get("available", False)  # type: ignore[union-attr]
    )
    results["all_ok"] = all_ok

    return results


def print_runtime_report() -> None:
    """Print a human-readable SU2 runtime diagnostics report."""
    report = check_full_runtime()

    print("=" * 60)
    print("  SU2 MCP Runtime Check")
    print("=" * 60)
    print(f"  Python:      {report['python']}")
    print(f"  Platform:    {report['platform']}")
    print()

    su2 = report.get("su2", {})
    if isinstance(su2, dict):
        for binary in su2.get("binaries", []):
            if isinstance(binary, dict):
                ok = binary.get("available", False)
                marker = "+" if ok else "x"
                name = binary.get("name", "?")
                path = binary.get("path", "not found")
                print(f"  [{marker}] {name:15s} {'OK':8s} {path}")
        if su2.get("version"):
            print(f"       Version: {su2['version']}")
    print()

    gmsh = report.get("gmsh", {})
    if isinstance(gmsh, dict):
        ok = gmsh.get("available", False)
        marker = "+" if ok else "x"
        print(f"  [{marker}] {'gmsh':15s} {'OK' if ok else 'MISSING':8s}", end="")
        if gmsh.get("cli") and gmsh["cli"] != "not on PATH":
            print(f"  [cli: {gmsh['cli']}]", end="")
        if gmsh.get("python_api"):
            print("  [python API: yes]", end="")
        print()

    print()
    if report.get("all_ok"):
        print("  All dependencies found. SU2 CFD solver is ready.")
    else:
        print("  Some dependencies are missing.")
        print()
        print(INSTALL_GUIDE)

    print("=" * 60)
