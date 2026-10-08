"""Mesh generation from STEP files using Gmsh and a .geo template."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

from su2_mcp.tools.session import SESSION_MANAGER, _error


def _default_geo_content() -> str:
    """Return bundled .geo template content for STEP-to-SU2 meshing."""
    from importlib.resources import files

    pkg = files("su2_mcp.data")
    return (pkg / "box_volume_step.geo").read_text(encoding="utf-8")


def generate_mesh_from_step(
    session_id: str,
    step_base64: str | None = None,
    output_mesh_name: str = "mesh.su2",
    geo_template_path: str | None = None,
    gmsh_timeout_seconds: int = 600,
    surface_density: int = 30,
    farfield_factor: float = 10.0,
    surface_size_m: float | None = None,
    step_path: str | None = None,
) -> dict[str, object]:
    """Generate a 3D SU2 mesh from a STEP file and attach it to the given session.

    Give the STEP either as ``step_path`` (the ``cad_path`` returned by
    tigl export_configuration_cad; preferred, the servers share a machine) or
    as ``step_base64`` (the file content). Until 2026-10-08 only the content
    form existed, and a model-driven client that had to copy a 536,000-
    character string between two tools copied 528 of them.

    By default this runs the same aircraft mesher the CPACS adapter and the
    paper's runs use (Gmsh Python API: farfield box sized from the geometry,
    fragment against the imported solids, FARFIELD and WALL markers, a 3D
    algorithm fallback chain). It handles metre-scaled, multi-solid TiGL
    exports with intersecting wing and fuselage solids, which the static
    template cannot. Until 2026-09-30 the static millimetre-scaled template
    was the only path, and a colleague's integration could not mesh the D150
    through this endpoint at all.

    Sizing matches the adapter: ``surface_density`` is the span-based preset
    knob (laptop 30, workstation 80, industry 200), and ``surface_size_m``
    is the absolute chord-based cell size that takes precedence when given.

    Pass ``geo_template_path`` to use a custom .geo template through the
    gmsh CLI instead (the template must Merge "model.step" and define
    FARFIELD and WALL physical surfaces).

    Args:
        session_id: Existing SU2 session (create_su2_session first).
        step_base64: Base64-encoded STEP file content (the cad_base64 field
            from tigl export_configuration_cad with include_base64=true).
            Not needed when step_path is given.
        output_mesh_name: Filename for the mesh in the session workdir.
        geo_template_path: Optional path to a .geo file (CLI path).
        gmsh_timeout_seconds: Timeout for the gmsh CLI subprocess.
        surface_density: Span / near-field cell size ratio (default 30).
        farfield_factor: Farfield box extent in spans (default 10).
        surface_size_m: Absolute near-field cell size in metres; overrides
            surface_density when set.
        step_path: Path of the STEP file on this machine (the cad_path from
            tigl export_configuration_cad). Preferred over step_base64.

    Returns:
        Dict with mesh_path, success, and optional error.

    """
    try:
        SESSION_MANAGER.require(session_id)
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")

    # gmsh picks the writer from the extension; a bare name dies inside gmsh
    # with "Unknown output file format" (seen 2026-10-02 from a model-driven
    # client). The tool owns its output format, so it enforces the suffix.
    if not output_mesh_name.endswith(".su2"):
        output_mesh_name = f"{output_mesh_name}.su2"

    gmsh_exe = shutil.which("gmsh")
    if not gmsh_exe:
        return _error(
            "gmsh not found on PATH; install gmsh (for example via "
            "conda-forge) for STEP->SU2 meshing",
            error_type="missing_dependency",
        )

    if step_path is not None and step_base64 is not None:
        return _error(
            "Give the STEP as step_path or as step_base64, not both",
            error_type="invalid_input",
        )
    if step_path is not None:
        src = Path(step_path)
        if not src.is_file():
            return _error(
                f"step_path does not exist or is not a file: {step_path}",
                error_type="invalid_input",
                details="Pass the cad_path returned by tigl export_configuration_cad.",
            )
        step_bytes = src.read_bytes()
    elif step_base64 is not None:
        try:
            from su2_mcp.session_manager import _decode_base64_content

            step_bytes = _decode_base64_content(step_base64, "step_base64")
        except ValueError as exc:
            return _error(str(exc), error_type="invalid_input")
    else:
        return _error(
            "No STEP given: pass step_path (the cad_path from tigl "
            "export_configuration_cad) or step_base64",
            error_type="invalid_input",
        )

    if not step_bytes.lstrip().startswith(b"ISO-10303-21"):
        return _error(
            "STEP content does not start with ISO-10303-21; ensure the "
            "input is a valid STEP file",
            error_type="validation_error",
        )

    workdir = Path(tempfile.mkdtemp(prefix="su2_mesh_"))
    try:
        model_step = workdir / "model.step"
        model_step.write_bytes(step_bytes)

        if geo_template_path is None:
            from su2_mcp import cpacs_adapter as _adapter

            out_mesh = workdir / output_mesh_name
            _adapter._LAST_MESH_FAILURE.clear()
            ok = _adapter._mesh_step_with_gmsh(
                str(model_step),
                str(out_mesh),
                {
                    "surface_density": int(surface_density),
                    "farfield_factor": float(farfield_factor),
                    "surface_size_m": surface_size_m,
                    "algorithm_2d": 6,
                },
            )
            if not ok or not out_mesh.exists() or out_mesh.stat().st_size == 0:
                return _error(
                    "aircraft meshing failed",
                    error_type="meshing_failure",
                    details=_adapter._LAST_MESH_FAILURE.get("reason"),
                )
            mesh_bytes = out_mesh.read_bytes()
            mesh_b64 = base64.b64encode(mesh_bytes).decode("utf-8")
            mesh_path = SESSION_MANAGER.update_mesh(
                session_id, mesh_b64, output_mesh_name
            )
            return {
                "success": True,
                "mesh_path": str(mesh_path),
                "mesh_bytes": len(mesh_bytes),
                "mesher": "aircraft_auto (adapter gmsh API)",
                "surface_density": int(surface_density),
                "farfield_factor": float(farfield_factor),
                "surface_size_m": surface_size_m,
            }

        if geo_template_path:
            geo_path = Path(geo_template_path)
            if not geo_path.is_file():
                return _error(
                    "geo_template_path is not an existing file",
                    error_type="validation_error",
                )
            geo_content = geo_path.read_text(encoding="utf-8")

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
        mesh_bytes = out_mesh.read_bytes() if out_mesh.exists() else b""
        if not mesh_bytes.lstrip().startswith(b"NDIME"):
            # gmsh exits 0 and writes an empty file when the .geo failed
            # mid-script (seen 2026-09-30 with a tag collision in a caller's
            # template). An empty or malformed mesh must not become a
            # "successful" session mesh that SU2 then refuses cryptically.
            return _error(
                "gmsh exited 0 but produced no usable SU2 mesh (empty or "
                "missing NDIME header); the .geo template likely failed "
                "mid-script",
                error_type="runtime_error",
                details={
                    "mesh_bytes": len(mesh_bytes),
                    "stdout_tail": (proc.stdout or "")[-2000:],
                    "stderr_tail": (proc.stderr or "")[-2000:],
                },
            )
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
    and estimated solver runtime scaling factors to help diagnose latency.
    """
    try:
        record = SESSION_MANAGER.require(session_id)
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")

    # SessionRecord stores the mesh as `mesh_path`, an absolute Path or None.
    # This previously read `record.mesh_filename`, which does not exist on the
    # record, so every call raised AttributeError before reaching the parser.
    mesh_path = record.mesh_path
    if mesh_path is None or not mesh_path.exists():
        return _error("No mesh file found in session", error_type="not_found")

    stats: dict[str, object] = {
        "mesh_file": mesh_path.name,
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

        if n_elements > 0:
            est_per_iter_sec = n_elements * 0.002
            stats["estimated_runtime"] = {
                "per_iteration_sec": round(est_per_iter_sec, 2),
                "at_100_iterations_sec": round(est_per_iter_sec * 100, 1),
                "at_250_iterations_sec": round(est_per_iter_sec * 250, 1),
                "at_500_iterations_sec": round(est_per_iter_sec * 500, 1),
                "note": (
                    "Rough estimates for single-core Euler;"
                    " actual time varies with hardware,"
                    " CFL, and convergence"
                ),
            }

    except Exception as exc:
        stats["parse_error"] = str(exc)

    return stats


__all__ = ["analyze_mesh", "generate_mesh_from_step"]
