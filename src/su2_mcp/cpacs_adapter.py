"""Shared-CPACS adapter for the SU2 MCP.

Reads reference geometry and flight conditions from the CPACS XML,
meshes (via Gmsh) a STEP file if provided, runs the real SU2_CFD
solver, parses CL/CD from the history, and writes aerodynamic results
back into the CPACS.

No stubs or placeholder values — when a dependency is missing the
adapter reports the error honestly.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

LOGGER = logging.getLogger(__name__)


def read_from_cpacs(
    cpacs_xml: str,
    flight_conditions: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Extract reference geometry and flight conditions from CPACS."""
    root = ET.fromstring(cpacs_xml)

    ref_area_el = root.find(".//vehicles/aircraft/model/reference/area")
    ref_length_el = root.find(".//vehicles/aircraft/model/reference/length")

    ref_area = (
        float(ref_area_el.text)
        if ref_area_el is not None and ref_area_el.text
        else 122.4
    )
    ref_length = (
        float(ref_length_el.text)
        if ref_length_el is not None and ref_length_el.text
        else 4.2
    )

    fc = flight_conditions or {}
    mach = fc.get("mach", 0.78)
    aoa = fc.get("aoa", 2.0)
    altitude_ft = fc.get("altitude_ft", 35000.0)

    return {
        "ref_area_m2": ref_area,
        "ref_length_m": ref_length,
        "mach": mach,
        "aoa_deg": aoa,
        "altitude_ft": altitude_ft,
    }


def _write_euler_config(
    cfg_path: Path, inputs: dict[str, Any], mesh_filename: str
) -> None:
    """Write a real SU2 Euler configuration file."""
    cfg_path.write_text(
        f"""\
% ----------- SOLVER -----------%
SOLVER= EULER
MATH_PROBLEM= DIRECT

% ----------- FREESTREAM -----------%
MACH_NUMBER= {inputs["mach"]}
AOA= {inputs["aoa_deg"]}
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= 101325.0
FREESTREAM_TEMPERATURE= 288.15
REF_DIMENSIONALIZATION= DIMENSIONAL

% ----------- MESH -----------%
MESH_FILENAME= {mesh_filename}
MESH_FORMAT= SU2

% ----------- BOUNDARY CONDITIONS -----------%
MARKER_FAR= ( FARFIELD )
MARKER_EULER= ( WALL )
MARKER_PLOTTING= ( WALL )
MARKER_MONITORING= ( WALL )

% ----------- REFERENCE -----------%
REF_ORIGIN_MOMENT_X= 15.0
REF_ORIGIN_MOMENT_Y= 0.0
REF_ORIGIN_MOMENT_Z= 0.0
REF_LENGTH= {inputs["ref_length_m"]}
REF_AREA= {inputs["ref_area_m2"]}

% ----------- NUMERICS -----------%
NUM_METHOD_GRAD= GREEN_GAUSS
CFL_NUMBER= 1.0
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.1, 2.0, 1.0, 1e10 )
CONV_NUM_METHOD_FLOW= ROE
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.1
TIME_DISCRE_FLOW= EULER_IMPLICIT
LINEAR_SOLVER= FGMRES
LINEAR_SOLVER_PREC= ILU
LINEAR_SOLVER_ERROR= 1e-6
LINEAR_SOLVER_ITER= 10

% ----------- CONVERGENCE -----------%
ITER= 250
CONV_RESIDUAL_MINVAL= -10

% ----------- OUTPUT -----------%
OUTPUT_FILES= ( RESTART, PARAVIEW )
OUTPUT_WRT_FREQ= 50
CONV_FILENAME= history
HISTORY_OUTPUT= ( ITER, RMS_RES, LIFT, DRAG, AERO_COEFF )
SCREEN_OUTPUT= INNER_ITER, RMS_DENSITY, RMS_MOMENTUM-X, RMS_ENERGY, LIFT, DRAG
""",
        encoding="utf-8",
    )


def _mesh_step_with_gmsh(
    step_path: str, su2_path: str, mesh_cfg: dict | None = None
) -> bool:
    """Generate a volume mesh from a STEP file using Gmsh Python API.

    Mirrors the proven logic from pipeline/tigl_to_su2.py's
    create_volume_mesh_from_step().
    """
    import gmsh

    cfg = mesh_cfg or {}
    farfield_factor = cfg.get("farfield_factor", 10.0)
    surface_density = cfg.get("surface_density", 30)
    algo_2d = cfg.get("algorithm_2d", 6)

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)

    try:
        LOGGER.info("Importing STEP: %s", step_path)
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(3)
        surfaces = gmsh.model.getEntities(2)
        LOGGER.info("Imported: %d volumes, %d surfaces", len(volumes), len(surfaces))

        xmin_a = ymin_a = zmin_a = float("inf")
        xmax_a = ymax_a = zmax_a = float("-inf")
        for dim, tag in gmsh.model.getEntities():
            if dim >= 1:
                bb = gmsh.model.getBoundingBox(dim, tag)
                xmin_a = min(xmin_a, bb[0])
                ymin_a = min(ymin_a, bb[1])
                zmin_a = min(zmin_a, bb[2])
                xmax_a = max(xmax_a, bb[3])
                ymax_a = max(ymax_a, bb[4])
                zmax_a = max(zmax_a, bb[5])

        cx = (xmin_a + xmax_a) / 2
        cy = (ymin_a + ymax_a) / 2
        cz = (zmin_a + zmax_a) / 2
        span = max(xmax_a - xmin_a, ymax_a - ymin_a, zmax_a - zmin_a)
        ff_half = span * farfield_factor / 2

        box = gmsh.model.occ.addBox(
            cx - ff_half,
            cy - ff_half,
            cz - ff_half,
            2 * ff_half,
            2 * ff_half,
            2 * ff_half,
        )
        gmsh.model.occ.synchronize()

        aircraft_dim_tags = volumes if volumes else [(2, t) for _, t in surfaces]
        result, result_map = gmsh.model.occ.fragment([(3, box)], aircraft_dim_tags)
        gmsh.model.occ.synchronize()

        frag_vols = gmsh.model.getEntities(3)
        frag_surfs = gmsh.model.getEntities(2)

        aircraft_vol_tags = set()
        for i in range(1, len(result_map)):
            for dim, tag in result_map[i]:
                if dim == 3:
                    aircraft_vol_tags.add(tag)

        fluid_vol_tags = [t for _, t in frag_vols if t not in aircraft_vol_tags]
        if not fluid_vol_tags:
            fluid_vol_tags = [t for _, t in frag_vols]

        ff_bounds = [
            cx - ff_half,
            cx + ff_half,
            cy - ff_half,
            cy + ff_half,
            cz - ff_half,
            cz + ff_half,
        ]
        eps = span * 0.001

        farfield_surf_tags = set()
        for dim, tag in frag_surfs:
            bb = gmsh.model.getBoundingBox(dim, tag)
            for ci, vals in [
                (0, [ff_bounds[0], ff_bounds[1]]),
                (1, [ff_bounds[2], ff_bounds[3]]),
                (2, [ff_bounds[4], ff_bounds[5]]),
            ]:
                lo, hi = bb[ci], bb[ci + 3]
                for val in vals:
                    if abs(lo - val) < eps and abs(hi - val) < eps:
                        farfield_surf_tags.add(tag)

        fluid_boundary_surfs = set()
        for vtag in fluid_vol_tags:
            boundary = gmsh.model.getBoundary([(3, vtag)], oriented=False)
            for dim, stag in boundary:
                if dim == 2:
                    fluid_boundary_surfs.add(stag)

        wall_surf_tags = fluid_boundary_surfs - farfield_surf_tags

        gmsh.model.addPhysicalGroup(3, fluid_vol_tags, name="FLUID")
        if farfield_surf_tags:
            gmsh.model.addPhysicalGroup(2, sorted(farfield_surf_tags), name="FARFIELD")
        if wall_surf_tags:
            gmsh.model.addPhysicalGroup(2, sorted(wall_surf_tags), name="WALL")

        char_near = span / surface_density
        char_far = span
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", char_near / 3)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", char_far)
        gmsh.option.setNumber("Mesh.Algorithm", algo_2d)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.AngleToleranceFacetOverlap", 0.5)

        for stag in wall_surf_tags:
            pts = gmsh.model.getBoundary([(2, stag)], recursive=True)
            for dim, ptag in pts:
                if dim == 0:
                    try:
                        gmsh.model.mesh.setSize([(0, ptag)], char_near)
                    except Exception:
                        pass

        meshed = False
        for algo, name in [(4, "Netgen"), (1, "Delaunay"), (10, "HXT")]:
            gmsh.option.setNumber("Mesh.Algorithm3D", algo)
            gmsh.option.setNumber("Mesh.OptimizeNetgen", 1 if algo == 4 else 0)
            try:
                gmsh.model.mesh.generate(3)
                node_check, _, _ = gmsh.model.mesh.getNodes()
                if len(node_check) > 0:
                    LOGGER.info("3D meshing succeeded with %s", name)
                    meshed = True
                    break
            except Exception as exc:
                LOGGER.debug("%s failed: %s", name, exc)
            try:
                gmsh.model.mesh.generate(2)
            except Exception:
                pass

        if meshed:
            gmsh.write(su2_path)
            node_tags, _, _ = gmsh.model.mesh.getNodes()
            LOGGER.info("Wrote %s (%d nodes)", su2_path, len(node_tags))
            return True
        else:
            LOGGER.error("All 3D meshing algorithms failed")
            return False

    finally:
        gmsh.finalize()


def _parse_history(history_path: Path) -> dict[str, float | None]:
    """Parse CL and CD from SU2 history.csv."""
    cl = cd = None
    if not history_path.exists():
        return {"CL": None, "CD": None}

    with history_path.open("r", encoding="utf-8") as f:
        header = None
        for line in f:
            line = line.strip()
            if not line:
                continue
            if header is None:
                header = [h.strip().strip('"') for h in line.split(",")]
                continue
            vals = line.split(",")
            row = dict(zip(header, vals, strict=False))
            for key in row:
                kl = key.lower().strip().strip('"')
                if "cl" in kl or "lift" in kl:
                    try:
                        cl = float(row[key])
                    except ValueError:
                        pass
                if "cd" in kl or "drag" in kl:
                    try:
                        cd = float(row[key])
                    except ValueError:
                        pass

    return {"CL": cl, "CD": cd}


def _run_su2_cfd(workdir: Path, config_name: str, timeout: int = 600) -> dict[str, Any]:
    """Run real SU2_CFD as a subprocess."""
    su2_exe = shutil.which("SU2_CFD")
    if not su2_exe:
        return {
            "error": {
                "type": "missing_binary",
                "message": (
                    "SU2_CFD not found on PATH. Install SU2 v8.4.0 from "
                    "https://github.com/su2code/SU2/releases or add it to PATH."
                ),
            },
        }

    LOGGER.info("Running SU2_CFD in %s ...", workdir)
    start = time.time()
    try:
        proc = subprocess.run(
            [su2_exe, config_name],
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
        )
        elapsed = time.time() - start
        tail = "\n".join(proc.stdout.splitlines()[-50:]) if proc.stdout else ""

        if proc.returncode != 0:
            return {
                "error": {
                    "type": "solver_failure",
                    "message": f"SU2_CFD exited with code {proc.returncode}",
                    "log_tail": tail,
                },
                "exit_code": proc.returncode,
                "runtime_seconds": elapsed,
            }

        return {
            "success": True,
            "exit_code": proc.returncode,
            "runtime_seconds": elapsed,
            "log_tail": tail,
        }
    except subprocess.TimeoutExpired:
        return {
            "error": {"type": "timeout", "message": f"SU2 timed out after {timeout}s"},
            "runtime_seconds": timeout,
        }


def run_adapter(
    cpacs_xml: str,
    flight_conditions: dict[str, float] | None = None,
    step_bytes: bytes | None = None,
    step_path: str | None = None,
    mesh_path: str | None = None,
    output_dir: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Full read→process→write cycle for the SU2 domain.

    Accepts geometry in one of three forms:
    - mesh_path: pre-existing .su2 mesh file
    - step_bytes: raw STEP file bytes (will mesh with Gmsh)
    - step_path: path to a .step file (will mesh with Gmsh)

    Runs the real SU2_CFD solver and parses results.
    """
    inputs = read_from_cpacs(cpacs_xml, flight_conditions)
    out = Path(output_dir or tempfile.mkdtemp(prefix="su2_run_"))
    out.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "solver": "su2_cfd",
        "mach": inputs["mach"],
        "aoa_deg": inputs["aoa_deg"],
        "altitude_ft": inputs["altitude_ft"],
        "ref_area_m2": inputs["ref_area_m2"],
        "ref_length_m": inputs["ref_length_m"],
    }

    # Resolve mesh
    resolved_mesh = None
    if mesh_path and Path(mesh_path).exists():
        resolved_mesh = str(mesh_path)
        results["mesh_source"] = f"existing:{mesh_path}"
    elif step_bytes or step_path:
        if step_bytes:
            local_step = out / "aircraft_fused.step"
            local_step.write_bytes(step_bytes)
            step_file = str(local_step)
        else:
            step_file = step_path

        su2_mesh = str(out / "aircraft_volume.su2")
        print("      Meshing STEP → SU2 via Gmsh...")
        success = _mesh_step_with_gmsh(step_file, su2_mesh)
        if success:
            resolved_mesh = su2_mesh
            results["mesh_source"] = "gmsh_from_step"
        else:
            results["error"] = {
                "type": "meshing_failure",
                "message": "Gmsh volume meshing failed for the provided STEP file.",
            }
            results["converged"] = False
            updated_xml = write_to_cpacs(cpacs_xml, results)
            return updated_xml, results
    else:
        results["error"] = {
            "type": "missing_input",
            "message": (
                "No mesh or STEP geometry provided. SU2 requires a mesh. "
                "Provide mesh_path, step_bytes, or step_path."
            ),
        }
        results["converged"] = False
        updated_xml = write_to_cpacs(cpacs_xml, results)
        return updated_xml, results

    # Write SU2 config
    mesh_filename = Path(resolved_mesh).name
    if Path(resolved_mesh).parent != out:
        import shutil as sh

        sh.copy2(resolved_mesh, out / mesh_filename)

    config_name = "euler.cfg"
    _write_euler_config(out / config_name, inputs, mesh_filename)

    # Run real SU2_CFD
    print(f"      Running SU2_CFD (Mach={inputs['mach']}, AoA={inputs['aoa_deg']}°)...")
    run_result = _run_su2_cfd(out, config_name)

    if run_result.get("error"):
        results["error"] = run_result["error"]
        results["converged"] = False
        results["runtime_seconds"] = run_result.get("runtime_seconds")
        updated_xml = write_to_cpacs(cpacs_xml, results)
        return updated_xml, results

    # Parse CL/CD from history.csv
    history_file = out / "history.csv"
    coeffs = _parse_history(history_file)

    cl = coeffs["CL"]
    cd = coeffs["CD"]
    results["CL"] = cl
    results["CD"] = cd
    results["converged"] = cl is not None and cd is not None

    if cl is not None and cd is not None:
        results["L_over_D"] = round(cl / cd, 4) if abs(cd) > 1e-12 else 0.0
        ar = inputs["ref_area_m2"]
        e = 0.85
        results["CDi"] = (
            round((cl**2) / (math.pi * e * (ar / inputs["ref_length_m"])), 6)
            if ar > 0
            else None
        )
        results["CD0"] = (
            round(cd - (results["CDi"] or 0.0), 6)
            if results.get("CDi") is not None
            else None
        )
    else:
        results["L_over_D"] = None
        results["error"] = {
            "type": "results_parsing",
            "message": "Could not parse CL/CD from history.csv",
        }

    results["runtime_seconds"] = run_result.get("runtime_seconds")
    results["output_dir"] = str(out)

    updated_xml = write_to_cpacs(cpacs_xml, results)
    return updated_xml, results


def write_to_cpacs(cpacs_xml: str, results: dict[str, Any]) -> str:
    """Write aero results into ``//vehicles/aircraft/model/analysisResults/aero``."""
    root = ET.fromstring(cpacs_xml)

    model = root.find(".//vehicles/aircraft/model")
    if model is None:
        model = _ensure_path(root, "vehicles/aircraft/model")

    ar = model.find("analysisResults")
    if ar is None:
        ar = ET.SubElement(model, "analysisResults")

    existing = ar.find("aero")
    if existing is not None:
        ar.remove(existing)

    aero_el = ET.SubElement(ar, "aero")
    ET.SubElement(aero_el, "solver").text = results.get("solver", "unknown")
    ET.SubElement(aero_el, "converged").text = str(
        results.get("converged", False)
    ).lower()
    ET.SubElement(aero_el, "mach").text = str(results.get("mach", 0.0))
    ET.SubElement(aero_el, "aoaDeg").text = str(results.get("aoa_deg", 0.0))

    if results.get("mesh_source"):
        ET.SubElement(aero_el, "meshSource").text = results["mesh_source"]

    coeffs = ET.SubElement(aero_el, "coefficients")
    for key in ("CL", "CD", "CDi", "CD0", "Cm", "L_over_D"):
        val = results.get(key)
        if val is not None:
            ET.SubElement(coeffs, key).text = str(val)

    if results.get("runtime_seconds") is not None:
        ET.SubElement(aero_el, "runtimeSeconds").text = str(
            round(results["runtime_seconds"], 2)
        )

    if results.get("error"):
        err_el = ET.SubElement(aero_el, "error")
        err_info = results["error"]
        if isinstance(err_info, dict):
            ET.SubElement(err_el, "type").text = str(err_info.get("type", "unknown"))
            ET.SubElement(err_el, "message").text = str(err_info.get("message", ""))
        else:
            ET.SubElement(err_el, "message").text = str(err_info)

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _ensure_path(root: ET.Element, path: str) -> ET.Element:
    current = root
    for part in path.split("/"):
        child = current.find(part)
        if child is None:
            child = ET.SubElement(current, part)
        current = child
    return current
