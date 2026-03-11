"""Mesh generation from STEP (e.g. from TiGL export) using Gmsh + geo template."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

from su2_mcp_server.tools.session import SESSION_MANAGER, _error


def _default_geo_content() -> str:
    """Return default .geo template content (aircraft surface loop + farfield box -> SU2)."""
    from importlib.resources import files
    pkg = files("su2_mcp_server.data")
    return (pkg / "box_volume_step.geo").read_text(encoding="utf-8")


def generate_mesh_from_step(
    session_id: str,
    step_base64: str,
    output_mesh_name: str = "mesh.su2",
    geo_template_path: str | None = None,
    gmsh_timeout_seconds: int = 600,
) -> dict[str, object]:
    """Generate a 3D SU2 mesh from a STEP file and attach it to the given session.

    Uses a .geo template that merges the STEP, builds an aircraft volume (surface
    loop -> volume), creates a farfield box, and meshes the fluid domain with
    FARFIELD and WALL markers. Requires the `gmsh` CLI to be on PATH.

    Args:
        session_id: Existing SU2 session (create_su2_session first).
        step_base64: Base64-encoded STEP file content (e.g. from TiGL export).
        output_mesh_name: Filename for the mesh in the session workdir (default mesh.su2).
        geo_template_path: Optional path to a .geo file; if omitted, bundled template is used.
        gmsh_timeout_seconds: Timeout for the gmsh subprocess.

    Returns:
        Dict with mesh_path, success, and optional error.
    """
    try:
        record = SESSION_MANAGER.require(session_id)
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")

    gmsh_exe = shutil.which("gmsh")
    if not gmsh_exe:
        return _error(
            "gmsh not found on PATH; install gmsh (e.g. conda install -c conda-forge gmsh) for STEP->SU2 meshing",
            error_type="missing_dependency",
        )

    try:
        step_bytes = base64.b64decode(step_base64, validate=True)
    except Exception as exc:
        return _error("Invalid step_base64", details=str(exc))

    if not step_bytes.lstrip().startswith(b"ISO-10303-21"):
        return _error(
            "STEP content does not start with ISO-10303-21; ensure the input is a valid STEP file",
            error_type="validation_error",
        )

    workdir = Path(tempfile.mkdtemp(prefix="su2_mesh_"))
    try:
        step_path = workdir / "model.step"
        step_path.write_bytes(step_bytes)

        if geo_template_path:
            geo_path = Path(geo_template_path)
            if not geo_path.is_file():
                return _error("geo_template_path is not an existing file", error_type="validation_error")
            geo_content = geo_path.read_text(encoding="utf-8")
        else:
            geo_content = _default_geo_content()

        geo_path = workdir / "mesh.geo"
        geo_path.write_text(geo_content, encoding="utf-8")

        out_mesh = workdir / output_mesh_name
        cmd = [gmsh_exe, "-3", str(geo_path), "-o", str(out_mesh), "-format", "su2"]
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=gmsh_timeout_seconds,
        )
        if proc.returncode != 0:
            return _error(
                "gmsh failed",
                details={
                    "returncode": proc.returncode,
                    "stdout": proc.stdout or "",
                    "stderr": proc.stderr or "",
                },
            )
        if not out_mesh.exists():
            return _error("gmsh did not produce the expected mesh file", error_type="runtime_error")

        mesh_bytes = out_mesh.read_bytes()
        mesh_b64 = base64.b64encode(mesh_bytes).decode("utf-8")
        mesh_path = SESSION_MANAGER.update_mesh(session_id, mesh_b64, output_mesh_name)
        return {
            "success": True,
            "mesh_path": str(mesh_path),
            "mesh_size_bytes": len(mesh_bytes),
        }
    except subprocess.TimeoutExpired:
        return _error(
            "gmsh timed out",
            error_type="timeout",
            details=f"Timeout after {gmsh_timeout_seconds}s",
        )
    except Exception as exc:  # pragma: no cover
        return _error("Failed to generate mesh from STEP", details=str(exc))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def analyze_mesh(
    session_id: str,
) -> dict[str, object]:
    """Analyze the mesh attached to a session and return diagnostics.

    Reports element counts by type, node count, boundary marker summary,
    and estimated solver runtime scaling factors.  This helps diagnose
    latency issues (ref: GitHub issue #6) by correlating mesh size with
    expected compute time.
    """
    try:
        record = SESSION_MANAGER.require(session_id)
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")

    mesh_path = record.workdir / record.mesh_filename
    if not mesh_path.exists():
        return _error("No mesh file found in session", error_type="not_found")

    stats: dict[str, object] = {
        "mesh_file": record.mesh_filename,
        "file_size_bytes": mesh_path.stat().st_size,
    }

    try:
        text = mesh_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        n_points = 0
        n_elements = 0
        element_types: dict[str, int] = {}
        markers: list[dict[str, object]] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("NPOIN=") or line.startswith("NPOIN ="):
                n_points = int(line.split("=")[1].strip().split()[0])
            elif line.startswith("NELEM=") or line.startswith("NELEM ="):
                n_elements = int(line.split("=")[1].strip().split()[0])
                for j in range(i + 1, min(i + 1 + n_elements, len(lines))):
                    etype = lines[j].strip().split()[0] if lines[j].strip() else ""
                    element_types[etype] = element_types.get(etype, 0) + 1
            elif line.startswith("MARKER_TAG=") or line.startswith("MARKER_TAG ="):
                tag = line.split("=")[1].strip()
                i += 1
                if i < len(lines):
                    nelem_line = lines[i].strip()
                    if nelem_line.startswith("MARKER_ELEMS"):
                        marker_elems = int(nelem_line.split("=")[1].strip())
                        markers.append({"tag": tag, "elements": marker_elems})
            i += 1

        stats["nodes"] = n_points
        stats["volume_elements"] = n_elements
        stats["element_types"] = element_types
        stats["markers"] = markers

        # Rough runtime estimates (Euler solver on a single core)
        # Based on empirical data: ~0.001-0.005 sec/element/iteration
        if n_elements > 0:
            est_per_iter_sec = n_elements * 0.002
            stats["estimated_runtime"] = {
                "per_iteration_sec": round(est_per_iter_sec, 2),
                "at_100_iterations_sec": round(est_per_iter_sec * 100, 1),
                "at_250_iterations_sec": round(est_per_iter_sec * 250, 1),
                "at_500_iterations_sec": round(est_per_iter_sec * 500, 1),
                "note": "Rough estimates for single-core Euler; actual time varies with hardware, CFL, and convergence",
            }

    except Exception as exc:
        stats["parse_error"] = str(exc)

    return stats


__all__ = ["generate_mesh_from_step", "analyze_mesh"]
