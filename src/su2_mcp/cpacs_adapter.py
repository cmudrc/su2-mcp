"""Shared-CPACS adapter for the SU2 MCP.

Reads reference geometry and flight conditions from the CPACS XML,
meshes (via Gmsh) a STEP file if provided, runs the real SU2_CFD
solver, parses CL/CD from the history, and writes aerodynamic results
back into the CPACS.

No stubs or placeholder values — when a dependency is missing the
adapter reports the error honestly.
"""

from __future__ import annotations

import importlib.metadata
import logging
import math
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

LOGGER = logging.getLogger(__name__)


# Mesh presets controlling Gmsh density and SU2 iteration budget.
# Tuned so that "laptop" matches the historical default behaviour and the
# higher tiers approach production fidelity for transonic transport Euler.
MESH_PRESETS: dict[str, dict[str, Any]] = {
    "laptop": {
        "surface_density": 30,
        "farfield_factor": 10.0,
        "iter": 250,
        "wall_timeout_seconds": 600,
        "label": "laptop (default; ~50k cells; ~15s)",
    },
    "workstation": {
        "surface_density": 80,
        "farfield_factor": 10.0,
        "iter": 400,
        "wall_timeout_seconds": 1800,
        "label": "workstation (~300k cells; ~5-10min)",
    },
    "industry": {
        "surface_density": 200,
        "farfield_factor": 15.0,
        "iter": 800,
        "wall_timeout_seconds": 7200,
        "label": "industry-grade (~2M cells; ~30-90min)",
    },
}


def resolve_preset(name: str | None) -> dict[str, Any]:
    """Look up a mesh/run preset; default to laptop if unknown."""
    if not name:
        return dict(MESH_PRESETS["laptop"])
    if name not in MESH_PRESETS:
        LOGGER.warning("Unknown mesh preset %r; falling back to laptop.", name)
        return dict(MESH_PRESETS["laptop"])
    return dict(MESH_PRESETS[name])


def _wing_half_span(wing: ET.Element) -> float:
    """Largest |y| of any section origin, resolving CPACS section placement.

    CPACS places a wing section either through a chain of ``positionings``
    (each giving a length, sweep and dihedral from a ``fromSectionUID``) or
    through the section's own ``transformation/translation``, or both. The
    D150 uses the chain with zero translations; other DLR reference models use
    translations with empty or zero-length positionings. Summing positioning
    lengths alone therefore read one model's tailplane chain as its main wing.
    """
    sections = wing.findall(".//sections/section")
    trans: dict[str, tuple[float, float, float]] = {}
    for sec in sections:
        uid = sec.get("uID") or ""
        t = sec.find("transformation/translation")
        if t is None:
            trans[uid] = (0.0, 0.0, 0.0)
        else:
            trans[uid] = tuple(float(t.findtext(k) or 0.0) for k in ("x", "y", "z"))

    # Resolve the positioning chain: position(to) = position(from) + length * direction.
    pos: dict[str, tuple[float, float, float]] = {}
    pending = list(wing.findall(".//positionings/positioning"))
    for _ in range(len(pending) + 1):
        if not pending:
            break
        rest = []
        for pz in pending:
            to_uid = pz.findtext("toSectionUID") or ""
            from_uid = pz.findtext("fromSectionUID")
            base = (0.0, 0.0, 0.0) if not from_uid else pos.get(from_uid)
            if base is None:
                rest.append(pz)
                continue
            try:
                length = float(pz.findtext("length") or 0.0)
                sweep = math.radians(float(pz.findtext("sweepAngle") or 0.0))
                dihedral = math.radians(float(pz.findtext("dihedralAngle") or 0.0))
            except ValueError:
                continue
            pos[to_uid] = (
                base[0] + length * math.sin(sweep),
                base[1] + length * math.cos(sweep) * math.cos(dihedral),
                base[2] + length * math.cos(sweep) * math.sin(dihedral),
            )
        pending = rest

    half = 0.0
    for uid in {*trans, *pos}:
        y = pos.get(uid, (0.0, 0.0, 0.0))[1] + trans.get(uid, (0.0, 0.0, 0.0))[1]
        half = max(half, abs(y))
    return half


def _wing_aspect_ratio(
    root: ET.Element, ref_area_m2: float | None
) -> tuple[float | None, str]:
    """Aspect ratio b^2 / S_ref from the file's own wing geometry.

    Prefers an explicit ``reference/aspectRatio``. Otherwise each wing's span
    is taken from its resolved section positions (see ``_wing_half_span``),
    doubled when the wing is declared symmetric, and the largest span is the
    main wing. Returns ``(None, reason)`` when it cannot be computed. It never
    guesses.
    """
    if not ref_area_m2 or ref_area_m2 <= 0:
        return None, "no reference area in the file"
    ar_el = root.find(".//vehicles/aircraft/model/reference/aspectRatio")
    if ar_el is not None and ar_el.text:
        try:
            return float(ar_el.text), "cpacs:reference/aspectRatio"
        except ValueError:
            pass
    best_span = 0.0
    for wing in root.findall(".//vehicles/aircraft/model/wings/wing"):
        half = _wing_half_span(wing)
        span = 2.0 * half if wing.get("symmetry") else half
        best_span = max(best_span, span)
    if best_span <= 0.0:
        return None, "no wing section positions in the file"
    source = f"cpacs:wing sections, span {best_span:.2f} m"
    return round(best_span * best_span / ref_area_m2, 3), source


def read_from_cpacs(
    cpacs_xml: str,
    flight_conditions: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Extract reference geometry and flight conditions from CPACS."""
    root = ET.fromstring(cpacs_xml)

    ref_area_el = root.find(".//vehicles/aircraft/model/reference/area")
    ref_length_el = root.find(".//vehicles/aircraft/model/reference/length")

    # No defaults. SU2 normalises lift and drag by the reference area, so a
    # substituted area rescales every coefficient the run reports. 122.4 m2 and
    # 4.2 m are the D150's, and defaulting to them meant any file missing the
    # reference block was silently reported in D150 units.
    ref_area = (
        float(ref_area_el.text)
        if ref_area_el is not None and ref_area_el.text
        else None
    )
    ref_length = (
        float(ref_length_el.text)
        if ref_length_el is not None and ref_length_el.text
        else None
    )

    fc = flight_conditions or {}
    mach = fc.get("mach", 0.78)
    aoa = fc.get("aoa", 2.0)
    altitude_ft = fc.get("altitude_ft", 35000.0)

    aspect_ratio, aspect_ratio_source = _wing_aspect_ratio(root, ref_area)

    return {
        "ref_area_m2": ref_area,
        "ref_length_m": ref_length,
        "aspect_ratio": aspect_ratio,
        "aspect_ratio_source": aspect_ratio_source,
        "mach": mach,
        "aoa_deg": aoa,
        "altitude_ft": altitude_ft,
    }


def _write_euler_config(
    cfg_path: Path,
    inputs: dict[str, Any],
    mesh_filename: str,
    iter_cap: int = 250,
    cl_convergence_eps: float | None = None,
) -> None:
    """Write a real SU2 Euler configuration file.

    `iter_cap` is the hard iteration limit. If `cl_convergence_eps` is set
    (e.g. 1e-4), SU2 will also stop early when the standard deviation of
    LIFT over the last 100 iterations drops below that threshold — the
    right knob for adaptive mesh refinement (see SU2_TIMING_NOTE.md).
    """
    extra_conv = ""
    if cl_convergence_eps is not None:
        extra_conv = (
            "\n% --- early Cauchy convergence on LIFT ---\n"
            f"CONV_FIELD= LIFT\n"
            f"CONV_CAUCHY_ELEMS= 100\n"
            f"CONV_CAUCHY_EPS= {cl_convergence_eps}\n"
        )

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
ITER= {iter_cap}
CONV_RESIDUAL_MINVAL= -10{extra_conv}

% ----------- OUTPUT -----------%
OUTPUT_FILES= ( RESTART, PARAVIEW )
OUTPUT_WRT_FREQ= 50
CONV_FILENAME= history
HISTORY_OUTPUT= ( ITER, RMS_RES, LIFT, DRAG, AERO_COEFF )
SCREEN_OUTPUT= INNER_ITER, RMS_DENSITY, RMS_MOMENTUM-X, RMS_ENERGY, LIFT, DRAG
""",
        encoding="utf-8",
    )


#: No aircraft is this long. Larger extents mean the STEP is in millimetres.
_MAX_AIRCRAFT_EXTENT_M = 500.0

#: Why the last meshing attempt was refused, for the structured error.
_LAST_MESH_FAILURE: dict[str, str] = {}


def _set_mesh_failure(reason: str) -> None:
    _LAST_MESH_FAILURE["reason"] = reason
    LOGGER.error("Meshing refused: %s", reason)


def _mesh_step_with_gmsh(
    step_path: str, su2_path: str, mesh_cfg: dict[str, Any] | None = None
) -> bool:
    """Generate a volume mesh from a STEP file using Gmsh Python API.

    Mirrors the proven logic from pipeline/tigl_to_su2.py's
    create_volume_mesh_from_step().
    """
    import gmsh

    cfg = mesh_cfg or {}
    farfield_factor = cfg.get("farfield_factor", 10.0)
    surface_density = cfg.get("surface_density", 30)
    # Absolute near-wall cell size in metres. When given it replaces the
    # span-relative rule below, so a rung can be defined by cells across the
    # chord (size = chord / n) instead of cells across the span.
    surface_size_m = cfg.get("surface_size_m")
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

        # A STEP with faces but no closed solid cannot be subtracted from the
        # farfield box. Fragmenting the box with loose faces gives a domain
        # with no aircraft cavity: SU2 runs, and the numbers mean nothing.
        # This is exactly what happened to the F25 in March 2026. TiGL's own
        # exportFusedSTEP writes such shells (in millimetres, one wing half);
        # the tigl-mcp closed-solid export is the file to mesh.
        if not volumes:
            _set_mesh_failure(
                f"STEP contains no closed solids ({len(surfaces)} faces only); it "
                "cannot be volume-meshed. Export the geometry as closed solids "
                "(tigl-mcp docker_tigl_closed_solids) instead of TiGL's "
                "fused-shell STEP."
            )
            return False

        # Surface area of the aircraft solids as CAD, before anything is cut.
        # After meshing, the WALL marker must reproduce it: that is the test
        # that the wall really is the aircraft skin.
        cad_area = 0.0
        for dim, tag in volumes:
            for _fd, ftag in gmsh.model.getBoundary(
                [(dim, tag)], oriented=False, recursive=False
            ):
                cad_area += gmsh.model.occ.getMass(2, abs(ftag))

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
        # REF_AREA is in square metres. A body several hundred metres long is
        # not an aircraft; it is a millimetre file, and every coefficient would
        # come out scaled by a million.
        if span > _MAX_AIRCRAFT_EXTENT_M:
            _set_mesh_failure(
                f"geometry extent {span:.0f} exceeds {_MAX_AIRCRAFT_EXTENT_M:.0f} m; "
                "the STEP is not in metres (TiGL exports in millimetres) and cannot "
                "be normalised by the CPACS reference area."
            )
            return False
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

        if surface_size_m is not None:
            char_near = float(surface_size_m)
        else:
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
            # A 3-D generate() that fails part-way still leaves nodes behind,
            # so "some nodes exist" is not "the domain was meshed". Check the
            # mesh against the geometry it was supposed to wrap.
            wall = _su2_wall_area(su2_path)
            problem = _mesh_consistency_error(
                cad_area,
                wall["wetted_area_m2"] if wall else None,
                _count_su2_mesh_elements(su2_path),
                wall["wetted_area_wall_faces"] if wall else None,
            )
            if problem:
                _set_mesh_failure(problem)
                Path(su2_path).unlink(missing_ok=True)
                return False
            return True
        else:
            LOGGER.error("All 3D meshing algorithms failed")
            return False

    finally:
        gmsh.finalize()


#: The faceted wall is a lower bound on the CAD skin and converges to it
#: (D150: -0.9 % at 2.9k faces). Anything outside this band is not the aircraft.
_WALL_AREA_TOLERANCE = 0.15


def _mesh_consistency_error(
    cad_area_m2: float,
    wall_area_m2: float | None,
    n_volume_elements: int | None,
    n_wall_faces: int | None,
) -> str | None:
    """Explain why a written mesh cannot be the fluid domain around the CAD body.

    Returns None when the WALL marker's faceted area matches the CAD surface
    area within tolerance and the volume mesh is at least as large as the wall
    triangulation. Both failed for the F25 in September 2026: 5,871 tetrahedra
    against 15,342 wall faces, and a wall area of 2.3e7 m2 against 853 m2.
    """
    if wall_area_m2 is None or n_wall_faces is None:
        return "mesh has no WALL marker; the aircraft surface was not tagged."
    if cad_area_m2 > 0:
        rel = (wall_area_m2 - cad_area_m2) / cad_area_m2
        if abs(rel) > _WALL_AREA_TOLERANCE:
            return (
                f"WALL marker area {wall_area_m2:,.1f} m2 differs from the CAD "
                f"surface area {cad_area_m2:,.1f} m2 by {rel:+.0%}; the tagged wall "
                "is not the aircraft skin (boolean or tagging failure)."
            )
    if n_volume_elements is not None and n_volume_elements < n_wall_faces:
        return (
            f"only {n_volume_elements:,} volume elements for {n_wall_faces:,} wall "
            "faces; the 3-D mesh did not fill the domain."
        )
    return None


def _count_su2_wall_faces(su2_path: str, wall_tag: str = "WALL") -> int | None:
    """Count the surface elements on the WALL marker of an SU2 mesh.

    Returns None when the file cannot be read.
    """
    try:
        in_wall = False
        with open(su2_path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("MARKER_TAG"):
                    in_wall = wall_tag in line
                elif line.startswith("MARKER_ELEMS") and in_wall:
                    return int(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        return None
    return None


def _count_su2_mesh_elements(su2_path: Path | str) -> int | None:
    """Return the NELEM count from an SU2 ASCII mesh, or None on failure.

    SU2 ASCII meshes contain a ``NELEM= <n>`` header line; reading just that
    line keeps this cheap for the multi-million-cell meshes the open-ended
    refinement loop produces.
    """
    try:
        p = Path(su2_path)
        if not p.exists():
            return None
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("NELEM="):
                    return int(line.split("=", 1)[1].strip())
                if line.startswith("NELEM "):
                    return int(line.split()[1])
        return None
    except Exception:
        return None


#: VTK element types SU2 uses for boundary faces, and their node counts.
_SU2_SURFACE_NODES = {5: 3, 9: 4}


def _su2_wall_area(
    su2_path: Path | str, wall_markers: tuple[str, ...] = ("WALL",)
) -> dict[str, Any] | None:
    """Wetted area of the geometry as meshed: the summed area of the wall faces.

    Ron Engelbeck (Boeing), 2026-09: "sum up the surface area of the surface
    patches of your CFD mesh." That is all this does. It reads the boundary
    markers of the SU2 ASCII mesh that the run used and sums the triangle and
    quadrilateral areas on the wall marker(s). It is the area of the faceted
    surface SU2 actually saw, so on a coarse mesh it is a lower bound on the
    smooth surface (D150: 712.9 / 715.3 / 718.2 m2 at 2.9k / 9.8k / 51k wall
    faces against 719.2 m2 from the CAD faces). Nothing is smoothed or
    corrected. Mesh units are taken as metres, like REF_AREA.

    A mesh carrying a symmetry marker holds one side only; the area is then
    doubled and the result says so. Returns None when the file cannot be read
    or has no wall marker, never a guess.
    """
    try:
        p = Path(su2_path)
        points: list[tuple[float, float, float]] = []
        markers: dict[str, list[tuple[int, ...]]] = {}
        with p.open("r", encoding="utf-8", errors="ignore") as fh:
            it = iter(fh)
            for raw in it:
                line = raw.split("%", 1)[0].strip()
                if not line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key == "NDIME":
                    if int(val) != 3:
                        return None
                elif key == "NELEM":
                    n, got = int(val), 0
                    while got < n:
                        if next(it).strip():
                            got += 1
                elif key == "NPOIN":
                    n, got = int(val), 0
                    while got < n:
                        parts = next(it).split()
                        if not parts:
                            continue
                        points.append(
                            (float(parts[0]), float(parts[1]), float(parts[2]))
                        )
                        got += 1
                elif key == "MARKER_TAG":
                    tag = val.strip()
                    k2, _, v2 = next(it).partition("=")
                    if k2.strip() != "MARKER_ELEMS":
                        return None
                    m = int(v2)
                    elems: list[tuple[int, ...]] = []
                    while len(elems) < m:
                        parts = next(it).split()
                        if not parts:
                            continue
                        nn = _SU2_SURFACE_NODES.get(int(parts[0]))
                        if nn is None:
                            return None
                        elems.append(tuple(int(x) for x in parts[1 : 1 + nn]))
                    markers[tag] = elems
        walls = [w for w in wall_markers if w in markers]
        if not points or not walls:
            return None

        Pt = tuple[float, float, float]

        def tri(a: Pt, b: Pt, c: Pt) -> float:
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)

        area = 0.0
        n_faces = 0
        for w in walls:
            for e in markers[w]:
                q = [points[i] for i in e]
                area += tri(q[0], q[1], q[2]) + (
                    tri(q[0], q[2], q[3]) if len(q) == 4 else 0.0
                )
                n_faces += 1
        half = any("SYM" in tag.upper() for tag in markers)
        return {
            "wetted_area_m2": round(area * (2.0 if half else 1.0), 3),
            "wetted_area_source": (
                "sum of the wall-marker faces of the SU2 mesh the run used "
                "(faceted surface, lower bound on the smooth area)"
                + ("; symmetry marker present, one-side area doubled" if half else "")
            ),
            "wetted_area_wall_faces": n_faces,
            "wetted_area_wall_markers": walls,
        }
    except Exception:
        return None


def _detect_cauchy_triggered(
    log_tail: str, history_path: Path, iter_cap: int | None = None
) -> bool:
    """Report whether SU2 stopped on its convergence criterion rather than the cap.

    SU2 v8.4 prints no banner when the Cauchy criterion on LIFT is met; it
    simply stops iterating and exits successfully. The reliable record is the
    history file: a successful run that wrote fewer iterations than the cap
    stopped on its criterion (a diverged run exits non-zero and never reaches
    this check). The banner strings are kept for older SU2 versions.

    Found 2026-09-15: four refinement ladders (18 rungs) had this flag False on
    every rung although 16 of them stopped at 120-270 of 800 iterations.
    """
    if log_tail:
        lower = log_tail.lower()
        if any(
            m in lower
            for m in (
                "cauchy criteria satisfied",
                "convergence achieved",
                "cauchy convergence",
            )
        ):
            return True
    if iter_cap is None or not Path(history_path).exists():
        return False
    try:
        with Path(history_path).open("r", encoding="utf-8", errors="ignore") as fh:
            rows = sum(1 for i, line in enumerate(fh) if i > 0 and line.strip())
    except OSError:
        return False
    return 0 < rows < iter_cap


#: Exact SU2 history column names, in preference order, for each coefficient.
#: Matching is exact and case-insensitive. Substring matching is deliberately
#: not used: "CL/CD" contains both "cl" and "cd", and "Cl" is the rolling-moment
#: coefficient, so a substring rule silently returns the wrong column.
_HISTORY_COLUMNS: dict[str, tuple[str, ...]] = {
    "CL": ("cl", "cl(total)", "avg_cl", "lift_coefficient"),
    "CD": ("cd", "cd(total)", "avg_cd", "drag_coefficient"),
}


def _select_column(header: list[str], candidates: tuple[str, ...]) -> int | None:
    """Return the index of the first header entry exactly matching a candidate."""
    normalised = [h.strip().strip('"').strip().lower() for h in header]
    for candidate in candidates:
        if candidate in normalised:
            return normalised.index(candidate)
    return None


def _parse_history(history_path: Path) -> dict[str, float | None]:
    """Parse CL and CD from SU2 history.csv.

    Columns are matched by exact name rather than by substring. The previous
    implementation scanned for "cl"/"cd" anywhere in a column name and kept the
    last match, so a "CL/CD" efficiency column set both coefficients to the
    lift-to-drag ratio, and a rolling-moment "Cl" column was read as lift. Both
    produced plausible-looking numbers that were wrong.
    """
    if not history_path.exists():
        return {"CL": None, "CD": None}

    lines = [ln.strip() for ln in history_path.read_text(encoding="utf-8").splitlines()]
    rows = [ln for ln in lines if ln]
    if len(rows) < 2:
        return {"CL": None, "CD": None}

    header = rows[0].split(",")
    indices = {
        name: _select_column(header, candidates)
        for name, candidates in _HISTORY_COLUMNS.items()
    }

    result: dict[str, float | None] = {"CL": None, "CD": None}
    # Walk forward so the converged final iteration wins.
    for line in rows[1:]:
        values = line.split(",")
        for name, index in indices.items():
            if index is None or index >= len(values):
                continue
            try:
                result[name] = float(values[index])
            except ValueError:
                continue

    return result


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
    preset: str | None = None,
    iter_cap: int | None = None,
    cl_convergence_eps: float | None = None,
    wall_timeout_seconds: int | None = None,
    surface_density: int | None = None,
    farfield_factor: float | None = None,
    surface_size_m: float | None = None,
) -> tuple[str, dict[str, Any]]:
    """Full read→process→write cycle for the SU2 domain.

    Accepts geometry in one of three forms:
    - mesh_path: pre-existing .su2 mesh file (preset still controls iter cap)
    - step_bytes: raw STEP file bytes (will mesh with Gmsh at preset density)
    - step_path: path to a .step file (will mesh with Gmsh at preset density)

    The `preset` argument selects a (mesh density, iter cap, wall timeout)
    triple — "laptop" (default), "workstation", or "industry". Individual
    `iter_cap`, `cl_convergence_eps`, and `wall_timeout_seconds` arguments
    override the preset values when supplied. See MESH_PRESETS for details.

    Open-ended refinement: pass an explicit ``surface_density`` integer (and
    optionally ``farfield_factor``) to override the preset's Gmsh density
    without touching its iteration budget. This is the additive entry point
    used by the converged-delivery refinement loop (see
    ``scripts/run_converged_su2.py`` and ``SKILL_OPEN_ENDED_MESH.md``); the
    classic 3-preset path is unchanged when both overrides are ``None``.

    Runs the real SU2_CFD solver and parses results.
    """
    cfg = resolve_preset(preset)
    if iter_cap is not None:
        cfg["iter"] = iter_cap
    if wall_timeout_seconds is not None:
        cfg["wall_timeout_seconds"] = wall_timeout_seconds
    if surface_density is not None:
        if surface_density <= 0:
            raise ValueError(
                f"surface_density must be a positive int, got {surface_density!r}"
            )
        cfg["surface_density"] = int(surface_density)
    if farfield_factor is not None:
        if farfield_factor <= 0:
            raise ValueError(f"farfield_factor must be > 0, got {farfield_factor!r}")
        cfg["farfield_factor"] = float(farfield_factor)
    if surface_size_m is not None:
        if surface_size_m <= 0:
            raise ValueError(
                f"surface_size_m must be > 0 metres, got {surface_size_m!r}"
            )
        cfg["surface_size_m"] = float(surface_size_m)

    inputs = read_from_cpacs(cpacs_xml, flight_conditions)

    # SU2 normalises lift and drag by these, so they cannot be guessed: a
    # substituted reference area rescales every coefficient the run reports,
    # and the result still looks entirely plausible.
    missing_refs = [
        name
        for name, key in (("area", "ref_area_m2"), ("length", "ref_length_m"))
        if inputs.get(key) is None
    ]
    if missing_refs:
        return cpacs_xml, {
            "solver": "su2_cfd",
            "success": False,
            "error": {
                "type": "missing_input",
                "message": (
                    "Cannot run CFD: the CPACS file states no reference "
                    + " or ".join(missing_refs)
                    + "."
                ),
                "details": (
                    "Add //vehicles/aircraft/model/reference/"
                    + ", ".join(missing_refs)
                    + ". These are not defaulted: SU2 divides lift and drag by "
                    "the reference area, so a borrowed value rescales every "
                    "coefficient and the run still appears to succeed."
                ),
            },
        }

    out = Path(output_dir or tempfile.mkdtemp(prefix="su2_run_"))
    out.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "solver": "su2_cfd",
        "mach": inputs["mach"],
        "aoa_deg": inputs["aoa_deg"],
        "altitude_ft": inputs["altitude_ft"],
        "ref_area_m2": inputs["ref_area_m2"],
        "ref_length_m": inputs["ref_length_m"],
        "preset": preset or "laptop",
        "preset_label": cfg.get("label"),
        "iter_cap": cfg["iter"],
        "wall_timeout_seconds": cfg["wall_timeout_seconds"],
        "cl_convergence_eps": cl_convergence_eps,
        "requested_surface_density": cfg["surface_density"],
        "requested_farfield_factor": cfg["farfield_factor"],
        "requested_surface_size_m": cfg.get("surface_size_m"),
    }

    # Resolve mesh
    resolved_mesh = None
    if mesh_path and Path(mesh_path).exists():
        resolved_mesh = str(mesh_path)
        results["mesh_source"] = f"existing:{mesh_path}"
        nelem = _count_su2_mesh_elements(resolved_mesh)
        if nelem is not None:
            results["mesh_n_elem"] = nelem
    elif step_bytes or step_path:
        if step_bytes:
            local_step = out / "aircraft_fused.step"
            local_step.write_bytes(step_bytes)
            step_file = str(local_step)
        else:
            assert step_path is not None
            step_file = step_path

        su2_mesh = str(out / "aircraft_volume.su2")
        mesh_cfg = {
            "surface_density": cfg["surface_density"],
            "farfield_factor": cfg["farfield_factor"],
            "algorithm_2d": 6,
        }
        if cfg.get("surface_size_m") is not None:
            mesh_cfg["surface_size_m"] = cfg["surface_size_m"]
        size_note = (
            f"surface_size_m={mesh_cfg['surface_size_m']:.4f}"
            if "surface_size_m" in mesh_cfg
            else f"surface_density={mesh_cfg['surface_density']}"
        )
        print(
            f"      Meshing STEP → SU2 via Gmsh "
            f"(preset={results['preset']}, {size_note})..."
        )
        _LAST_MESH_FAILURE.clear()
        success = _mesh_step_with_gmsh(step_file, su2_mesh, mesh_cfg)
        if success:
            resolved_mesh = su2_mesh
            results["mesh_source"] = "gmsh_from_step"
            results["mesh_surface_density"] = mesh_cfg["surface_density"]
            results["mesh_farfield_factor"] = mesh_cfg["farfield_factor"]
            results["mesh_surface_size_m"] = mesh_cfg.get("surface_size_m")
            results["mesh_wall_faces"] = _count_su2_wall_faces(su2_mesh)
            nelem = _count_su2_mesh_elements(su2_mesh)
            if nelem is not None:
                results["mesh_n_elem"] = nelem
        else:
            results["error"] = {
                "type": "meshing_failure",
                "message": "Gmsh volume meshing failed for the provided STEP file.",
            }
            if _LAST_MESH_FAILURE.get("reason"):
                results["error"]["details"] = _LAST_MESH_FAILURE["reason"]
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

    # Wetted area of the geometry as meshed, for the mass-properties and
    # skin-friction stages downstream. Comes from the same faces SU2 solves on.
    wall_area = _su2_wall_area(resolved_mesh)
    if wall_area is not None:
        results.update(wall_area)

    # Write SU2 config
    mesh_filename = Path(resolved_mesh).name
    if Path(resolved_mesh).parent != out:
        import shutil as sh

        sh.copy2(resolved_mesh, out / mesh_filename)

    config_name = "euler.cfg"
    _write_euler_config(
        out / config_name,
        inputs,
        mesh_filename,
        iter_cap=cfg["iter"],
        cl_convergence_eps=cl_convergence_eps,
    )

    # Run real SU2_CFD
    print(
        f"      Running SU2_CFD (Mach={inputs['mach']}, AoA={inputs['aoa_deg']}°, "
        f"iter_cap={cfg['iter']}, timeout={cfg['wall_timeout_seconds']}s)..."
    )
    run_result = _run_su2_cfd(out, config_name, timeout=cfg["wall_timeout_seconds"])

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

    unphysical = (
        _check_coefficients(cl, cd) if (cl is not None and cd is not None) else None
    )
    if unphysical is not None:
        # Refuse to publish an impossible coefficient. Downstream tools size an
        # engine directly from CD, so letting this through turns one bad number
        # into a bad engine and then a bad mission.
        results["CL"] = None
        results["CD"] = None
        results["L_over_D"] = None
        results["converged"] = False
        results["error"] = unphysical
        results["raw_CL"] = cl
        results["raw_CD"] = cd
    elif cl is not None and cd is not None:
        results["L_over_D"] = round(cl / cd, 4) if abs(cd) > 1e-12 else 0.0
        # One Euler point gives CL and CD only. Splitting CD into induced and
        # parasite parts needs an aspect ratio and an Oswald efficiency, so the
        # split is an estimate and is labelled as one. It is not a fitted polar.
        #
        # Until 2026-09-10 this divided the reference AREA by the reference
        # LENGTH and used the result as the aspect ratio: 29.1 for the D150
        # against a real 9.4 from the file's own wing geometry. Induced drag
        # was understated about 3x, and the published k = 0.0129 was this
        # formula with that wrong quantity in it.
        ar = inputs.get("aspect_ratio")
        e = 0.85
        if ar is not None and ar > 0:
            cdi = round((cl**2) / (math.pi * e * ar), 6)
            results["CDi"] = cdi
            results["CD0"] = round(cd - cdi, 6)
            results["polar_method"] = "single_point_oswald_split"
            results["oswald_e"] = e
            results["aspect_ratio"] = ar
            results["aspect_ratio_source"] = inputs.get("aspect_ratio_source")
        else:
            results["CDi"] = None
            results["CD0"] = None
            results["polar_note"] = (
                "CD not split into CD0 and CDi: no aspect ratio could be "
                f"determined ({inputs.get('aspect_ratio_source')}). Supply a "
                "drag polar to the mission stage explicitly."
            )
    else:
        results["L_over_D"] = None
        results["error"] = {
            "type": "results_parsing",
            "message": "Could not parse CL/CD from history.csv",
        }

    results["runtime_seconds"] = run_result.get("runtime_seconds")
    results["output_dir"] = str(out)
    results["cauchy_triggered"] = _detect_cauchy_triggered(
        run_result.get("log_tail", ""), history_file, iter_cap=cfg["iter"]
    )

    updated_xml = write_to_cpacs(cpacs_xml, results)
    return updated_xml, results


#: A body cannot produce negative drag, and no aircraft in this regime reaches a
#: lift coefficient of a few tens. These are impossibility bounds, not accuracy
#: bounds: a value outside them means the run or the parse is broken, not that
#: the answer is imprecise. Anything inside them is passed through untouched.
_CD_MIN = 0.0
_CL_ABS_MAX = 20.0
_CD_ABS_MAX = 20.0


def _check_coefficients(cl: float, cd: float) -> dict[str, Any] | None:
    """Return a structured error if the coefficients are physically impossible."""
    if cd <= _CD_MIN:
        return {
            "type": "unphysical_result",
            "message": (
                f"SU2 returned a non-positive drag coefficient (CD={cd:.6g}). "
                "A closed body cannot produce negative drag."
            ),
            "details": (
                "Check that the mesh is in metres and matches REF_AREA in the "
                "config, that farfield boundary markers are correct, and that "
                "the solution converged. This value was not written to CPACS, "
                "because a later tool would size an engine from it."
            ),
        }
    if abs(cl) > _CL_ABS_MAX or abs(cd) > _CD_ABS_MAX:
        return {
            "type": "unphysical_result",
            "message": (
                f"SU2 returned coefficients outside any physically possible "
                f"range (CL={cl:.6g}, CD={cd:.6g})."
            ),
            "details": (
                "This usually means the force non-dimensionalisation is wrong: "
                "REF_AREA in the config and the actual meshed geometry disagree, "
                "or the mesh is not in metres. This value was not written to "
                "CPACS, because a later tool would size an engine from it."
            ),
        }
    return None


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
    if results.get("wetted_area_m2") is not None:
        ET.SubElement(aero_el, "wettedAreaM2").text = str(results["wetted_area_m2"])
        ET.SubElement(aero_el, "wettedAreaSource").text = str(
            results.get("wetted_area_source", "")
        )
        if results.get("wetted_area_wall_faces") is not None:
            ET.SubElement(aero_el, "wettedAreaWallFaces").text = str(
                results["wetted_area_wall_faces"]
            )

    coeffs = ET.SubElement(aero_el, "coefficients")
    for key in ("CL", "CD", "CDi", "CD0", "Cm", "L_over_D"):
        val = results.get(key)
        if val is not None:
            ET.SubElement(coeffs, key).text = str(val)
    # How CD0/CDi were obtained travels with them, so a reader of the file can
    # see that the split is a labelled estimate and what it assumed.
    for key, tag in (
        ("polar_method", "polarMethod"),
        ("oswald_e", "oswaldE"),
        ("aspect_ratio", "aspectRatio"),
        ("aspect_ratio_source", "aspectRatioSource"),
        ("polar_note", "polarNote"),
    ):
        val = results.get(key)
        if val is not None:
            ET.SubElement(coeffs, tag).text = str(val)

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

    if results.get("error"):
        modification = (
            "su2-mcp wrote analysisResults/aero (SU2 run failed; the error is "
            "recorded there)"
        )
    else:
        modification = (
            "su2-mcp wrote analysisResults/aero (Euler CFD coefficients, wetted area)"
        )
    _append_header_update(root, modification, _creator_label())

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _creator_label() -> str:
    """Return ``"su2-mcp <version>"`` for the header provenance entry.

    The version is read from the installed distribution metadata. When the
    package is not installed as a distribution it is reported as ``unknown``
    rather than guessed.
    """
    try:
        version = importlib.metadata.version("su2-mcp")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return f"su2-mcp {version}"


def _append_header_update(
    root: ET.Element, modification: str, creator: str
) -> ET.Element:
    """Record one write in the CPACS ``header/updates`` provenance list.

    CPACS keeps a running log of changes to a document in ``header/updates``.
    Appending an entry for every write lets a reader of the shared file see
    which tool wrote which section and when, without opening the run logs.

    ``header`` is created as the first child of ``cpacs`` when it is missing.
    ``updates`` is created when it is missing and placed directly after
    ``cpacsVersion``, else directly after ``version``, else at the end of the
    header, so the CPACS 3.x element order stays valid. Existing header
    children are never removed or reordered.

    The new ``update`` carries, in schema order: ``modification`` (one
    sentence saying what was written), ``creator`` (package name and
    version), ``timestamp`` (UTC, ISO 8601, seconds precision), ``version``
    (a running count, 1 + the number of existing entries) and
    ``cpacsVersion`` (copied from ``header/cpacsVersion``, else from
    ``header/version``, else left empty).
    """
    header = root.find("header")
    if header is None:
        header = ET.Element("header")
        root.insert(0, header)

    updates = header.find("updates")
    if updates is None:
        updates = ET.Element("updates")
        anchor = header.find("cpacsVersion")
        if anchor is None:
            anchor = header.find("version")
        if anchor is None:
            header.append(updates)
        else:
            header.insert(list(header).index(anchor) + 1, updates)

    running_version = len(updates.findall("update")) + 1
    cpacs_version = (
        header.findtext("cpacsVersion") or header.findtext("version") or ""
    ).strip()

    update = ET.SubElement(updates, "update")
    ET.SubElement(update, "modification").text = modification
    ET.SubElement(update, "creator").text = creator
    ET.SubElement(update, "timestamp").text = datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    ET.SubElement(update, "version").text = str(running_version)
    ET.SubElement(update, "cpacsVersion").text = cpacs_version
    return update


def _ensure_path(root: ET.Element, path: str) -> ET.Element:
    current = root
    for part in path.split("/"):
        child = current.find(part)
        if child is None:
            child = ET.SubElement(current, part)
        current = child
    return current
