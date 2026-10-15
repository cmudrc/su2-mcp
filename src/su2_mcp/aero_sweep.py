"""Reference angle-of-attack sweeps kept inside the CPACS file.

A sweep is a set of real SU2 runs of one aircraft on one mesh at one Mach
number, each at a different angle of attack, stored together with the mesh
they ran on, where and when they ran, and the two fits derived from them
(the drag polar CD = CD0 + k CL^2 and the lift curve CL = CL0 + a alpha).
It lives at ``//vehicles/aircraft/model/analysisResults/aeroSweep/sweep``,
one ``sweep`` element per mesh level, keyed by ``uID``. The single-point
``analysisResults/aero`` node that a live run writes is left alone, so a
quick run on the laptop never overwrites the reference table, and readers
that prefer the table (the mission adapter, the lookup tool) say so.

Every number in a sweep is a solver output. The fits and the lookups are
derived from those outputs and are labelled as derived wherever they are
returned (``derived_from`` names the runs they rest on).
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

SWEEP_PATH = "vehicles/aircraft/model/analysisResults/aeroSweep"
POINT_KEYS = (
    "aoa_deg",
    "CL",
    "CD",
    "L_over_D",
    "cauchy_triggered",
    "iterations",
    "runtime_seconds",
)
_POINT_TAGS = {
    "aoa_deg": "aoaDeg",
    "CL": "CL",
    "CD": "CD",
    "L_over_D": "L_over_D",
    "cauchy_triggered": "cauchyTriggered",
    "iterations": "iterations",
    "runtime_seconds": "runtimeSeconds",
}
_META_TAGS = (
    ("label", "label"),
    ("solver", "solver"),
    ("flow_model", "flowModel"),
    ("mesh_rule", "meshRule"),
    ("mesh_cells", "meshCells"),
    ("mesh_wall_faces", "meshWallFaces"),
    ("surface_size_m", "surfaceSizeM"),
    ("mach", "mach"),
    ("altitude_ft", "altitudeFt"),
    ("reference_area_m2", "referenceAreaM2"),
    ("machine", "machine"),
    ("computed_utc", "computedUtc"),
    ("source", "source"),
    ("note", "note"),
)


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0


def fit_polar(
    points: list[dict[str, Any]], aoa_max: float = 8.0
) -> dict[str, Any] | None:
    """Least-squares CD = CD0 + k CL^2 over the points with aoa <= aoa_max.

    Needs three points. Returns CD0, k, r_squared, n_points, the CL and
    angle ranges used, and the method, or None when there are too few points.
    """
    pts = [
        p
        for p in points
        if p.get("CL") is not None
        and p.get("CD") is not None
        and p["aoa_deg"] <= aoa_max
    ]
    if len(pts) < 3:
        return None
    cl = np.array([p["CL"] for p in pts], dtype=float)
    cd = np.array([p["CD"] for p in pts], dtype=float)
    A = np.column_stack([np.ones_like(cl), cl**2])
    coef, *_ = np.linalg.lstsq(A, cd, rcond=None)
    return {
        "CD0": float(coef[0]),
        "k": float(coef[1]),
        "r_squared": _r2(cd, A @ coef),
        "n_points": len(pts),
        "cl_range": [float(cl.min()), float(cl.max())],
        "aoa_range_deg": [
            min(p["aoa_deg"] for p in pts),
            max(p["aoa_deg"] for p in pts),
        ],
        "method": f"least squares CD = CD0 + k CL^2 over {len(pts)} runs with aoa <= {aoa_max:g} deg",
    }


def fit_lift_curve(
    points: list[dict[str, Any]], aoa_max: float = 8.0
) -> dict[str, Any] | None:
    """Least-squares CL = CL0 + a alpha (alpha in degrees) over aoa <= aoa_max."""
    pts = [p for p in points if p.get("CL") is not None and p["aoa_deg"] <= aoa_max]
    if len(pts) < 2:
        return None
    aoa = np.array([p["aoa_deg"] for p in pts], dtype=float)
    cl = np.array([p["CL"] for p in pts], dtype=float)
    A = np.column_stack([np.ones_like(aoa), aoa])
    coef, *_ = np.linalg.lstsq(A, cl, rcond=None)
    return {
        "CL0": float(coef[0]),
        "CL_alpha_per_deg": float(coef[1]),
        "r_squared": _r2(cl, A @ coef),
        "n_points": len(pts),
        "aoa_range_deg": [float(aoa.min()), float(aoa.max())],
        "method": f"least squares CL = CL0 + a alpha over {len(pts)} runs with aoa <= {aoa_max:g} deg",
    }


def build_sweep(
    uid: str,
    label: str,
    runs: list[dict[str, Any]],
    meta: dict[str, Any],
    aoa_fit_max: float = 8.0,
) -> dict[str, Any]:
    """Compose a sweep record from the server's run records and metadata.

    Runs with an error are dropped and listed under ``excluded``. ``meta``
    carries solver, flow_model, mesh_rule, mesh_cells, mesh_wall_faces,
    surface_size_m, mach, altitude_ft, reference_area_m2, machine, source,
    note; ``computed_utc`` is set now when absent.
    """
    good = sorted(
        (r for r in runs if not r.get("error") and r.get("CL") is not None),
        key=lambda r: r["aoa_deg"],
    )
    points = [{k: r.get(k) for k in POINT_KEYS} for r in good]
    sweep: dict[str, Any] = {"uid": uid, "label": label, **meta}
    sweep.setdefault("computed_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    sweep["points"] = points
    sweep["excluded"] = [
        {"aoa_deg": r.get("aoa_deg"), "error": r.get("error")}
        for r in runs
        if r.get("error")
    ]
    sweep["fit"] = {
        "polar": fit_polar(points, aoa_fit_max),
        "lift_curve": fit_lift_curve(points, aoa_fit_max),
    }
    return sweep


def _ensure(parent: ET.Element, tag: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    return el


def write_sweep_to_cpacs(
    cpacs_xml: str, sweep: dict[str, Any], creator: str | None = None
) -> str:
    """Write (or replace, by uID) one sweep under analysisResults/aeroSweep.

    The header gets a provenance line naming the sweep, its run count, mesh
    and Mach number, with the session suffix when there is one.
    """
    from su2_mcp.cpacs_adapter import _append_header_update, _creator_label

    root = ET.fromstring(cpacs_xml)
    model = root.find("vehicles/aircraft/model")
    if model is None:
        raise ValueError("No vehicles/aircraft/model element in this CPACS file")
    ar = _ensure(model, "analysisResults")
    container = _ensure(ar, "aeroSweep")
    for old in container.findall("sweep"):
        if old.get("uID") == sweep["uid"]:
            container.remove(old)
    el = ET.SubElement(container, "sweep", {"uID": str(sweep["uid"])})
    for key, tag in _META_TAGS:
        if sweep.get(key) is not None:
            ET.SubElement(el, tag).text = str(sweep[key])
    pts_el = ET.SubElement(el, "points")
    for p in sweep.get("points", []):
        p_el = ET.SubElement(pts_el, "point")
        for key, tag in _POINT_TAGS.items():
            if p.get(key) is not None:
                ET.SubElement(p_el, tag).text = (
                    str(p[key]).lower() if isinstance(p[key], bool) else str(p[key])
                )
    if sweep.get("excluded"):
        ex_el = ET.SubElement(el, "excluded")
        for x in sweep["excluded"]:
            x_el = ET.SubElement(ex_el, "run")
            ET.SubElement(x_el, "aoaDeg").text = str(x.get("aoa_deg"))
            ET.SubElement(x_el, "error").text = str(x.get("error"))
    fit = sweep.get("fit") or {}
    fit_el = ET.SubElement(el, "fit")
    if fit.get("polar"):
        pol = fit["polar"]
        p_el = ET.SubElement(fit_el, "polar")
        for tag, key in (
            ("CD0", "CD0"),
            ("k", "k"),
            ("rSquared", "r_squared"),
            ("nPoints", "n_points"),
            ("method", "method"),
        ):
            ET.SubElement(p_el, tag).text = str(pol[key])
        ET.SubElement(
            p_el, "clRange"
        ).text = f"{pol['cl_range'][0]:.6g} {pol['cl_range'][1]:.6g}"
        ET.SubElement(
            p_el, "aoaRangeDeg"
        ).text = f"{pol['aoa_range_deg'][0]:g} {pol['aoa_range_deg'][1]:g}"
    if fit.get("lift_curve"):
        lc = fit["lift_curve"]
        l_el = ET.SubElement(fit_el, "liftCurve")
        for tag, key in (
            ("CL0", "CL0"),
            ("CLalphaPerDeg", "CL_alpha_per_deg"),
            ("rSquared", "r_squared"),
            ("nPoints", "n_points"),
            ("method", "method"),
        ):
            ET.SubElement(l_el, tag).text = str(lc[key])
        ET.SubElement(
            l_el, "aoaRangeDeg"
        ).text = f"{lc['aoa_range_deg'][0]:g} {lc['aoa_range_deg'][1]:g}"
    modification = (
        f"su2-mcp wrote analysisResults/aeroSweep/{sweep['uid']} ({len(sweep.get('points', []))} Euler runs at "
        f"Mach {sweep.get('mach')}, {sweep.get('mesh_rule')}, {sweep.get('mesh_cells')} cells, {sweep.get('machine')})"
    )
    _append_header_update(root, modification, creator or _creator_label())
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _num(text: str | None) -> float | None:
    try:
        return float(text) if text is not None and text.strip() else None
    except ValueError:
        return None


def read_sweeps(cpacs_xml: str) -> list[dict[str, Any]]:
    """All sweeps in the file, points sorted by angle, fits parsed back."""
    root = ET.fromstring(cpacs_xml)
    container = root.find(SWEEP_PATH)
    if container is None:
        return []
    out = []
    for el in container.findall("sweep"):
        sweep: dict[str, Any] = {"uid": el.get("uID")}
        for key, tag in _META_TAGS:
            txt = el.findtext(tag)
            if txt is None:
                continue
            sweep[key] = (
                _num(txt)
                if key
                in (
                    "mesh_cells",
                    "mesh_wall_faces",
                    "surface_size_m",
                    "mach",
                    "altitude_ft",
                    "reference_area_m2",
                )
                else txt
            )
        if sweep.get("mesh_cells") is not None:
            sweep["mesh_cells"] = int(sweep["mesh_cells"])
        points = []
        for p_el in el.findall("points/point"):
            p = {}
            for key, tag in _POINT_TAGS.items():
                txt = p_el.findtext(tag)
                if txt is None:
                    continue
                if key == "cauchy_triggered":
                    p[key] = txt.strip().lower() == "true"
                elif key == "iterations":
                    p[key] = int(float(txt))
                else:
                    p[key] = _num(txt)
            points.append(p)
        sweep["points"] = sorted(points, key=lambda p: p["aoa_deg"])
        fit: dict[str, Any] = {"polar": None, "lift_curve": None}
        pol = el.find("fit/polar")
        if pol is not None:
            fit["polar"] = {
                "CD0": _num(pol.findtext("CD0")),
                "k": _num(pol.findtext("k")),
                "r_squared": _num(pol.findtext("rSquared")),
                "n_points": int(float(pol.findtext("nPoints") or 0)),
                "method": pol.findtext("method"),
                "cl_range": [
                    float(x) for x in (pol.findtext("clRange") or "0 0").split()
                ],
                "aoa_range_deg": [
                    float(x) for x in (pol.findtext("aoaRangeDeg") or "0 0").split()
                ],
            }
        lc = el.find("fit/liftCurve")
        if lc is not None:
            fit["lift_curve"] = {
                "CL0": _num(lc.findtext("CL0")),
                "CL_alpha_per_deg": _num(lc.findtext("CLalphaPerDeg")),
                "r_squared": _num(lc.findtext("rSquared")),
                "n_points": int(float(lc.findtext("nPoints") or 0)),
                "method": lc.findtext("method"),
                "aoa_range_deg": [
                    float(x) for x in (lc.findtext("aoaRangeDeg") or "0 0").split()
                ],
            }
        sweep["fit"] = fit
        out.append(sweep)
    return out


def _interp(
    points: list[dict[str, Any]], x_key: str, x: float, y_keys: tuple[str, ...]
) -> dict[str, Any]:
    """Piecewise-linear interpolation in x_key, naming the two runs used."""
    pts = sorted(
        (p for p in points if p.get(x_key) is not None), key=lambda p: p[x_key]
    )
    xs = [p[x_key] for p in pts]
    if not pts or x < xs[0] - 1e-9 or x > xs[-1] + 1e-9:
        return {
            "error": {
                "type": "outside_stored_range",
                "message": f"{x_key} = {x:g} is outside the stored runs ({xs[0]:g} to {xs[-1]:g}); nothing is extrapolated."
                if pts
                else "no stored runs",
            }
        }
    for p in pts:
        if abs(p[x_key] - x) < 1e-9:
            return {
                **{k: p.get(k) for k in y_keys},
                "basis": "exact",
                "derived_from": [f"stored run at aoa {p['aoa_deg']:g} deg"],
            }
    for lo, hi in zip(pts, pts[1:]):
        if lo[x_key] <= x <= hi[x_key]:
            t = (x - lo[x_key]) / (hi[x_key] - lo[x_key])
            out = {
                k: (lo[k] + t * (hi[k] - lo[k]))
                if lo.get(k) is not None and hi.get(k) is not None
                else None
                for k in y_keys
            }
            out["basis"] = f"linear interpolation in {x_key} between two stored runs"
            out["derived_from"] = [
                f"stored run at aoa {lo['aoa_deg']:g} deg",
                f"stored run at aoa {hi['aoa_deg']:g} deg",
            ]
            return out
    return {"error": {"type": "outside_stored_range", "message": "no bracketing runs"}}


def lookup(
    sweep: dict[str, Any], at_aoa_deg: float | None = None, at_cl: float | None = None
) -> dict[str, Any]:
    """Values from a stored sweep at a given angle or lift coefficient.

    At an angle: CL, CD and L/D, exact when a run exists at that angle, else
    interpolated between the two neighbouring runs. At a lift coefficient:
    the angle that gives it (inverse interpolation on CL, which must rise
    with angle over the stored range), and CD and L/D at that CL. Nothing is
    extrapolated outside the stored runs.
    """
    points = sweep.get("points", [])
    out: dict[str, Any] = {
        "sweep": sweep.get("uid"),
        "label": sweep.get("label"),
        "mesh_cells": sweep.get("mesh_cells"),
        "mach": sweep.get("mach"),
        "n_runs": len(points),
        "aoa_range_deg": [points[0]["aoa_deg"], points[-1]["aoa_deg"]]
        if points
        else None,
    }
    if at_aoa_deg is not None:
        res = _interp(points, "aoa_deg", float(at_aoa_deg), ("CL", "CD", "L_over_D"))
        out["at_aoa_deg"] = {"aoa_deg": float(at_aoa_deg), **res}
    if at_cl is not None:
        # inverse on CL: use the rising part of the lift curve only
        rising = []
        for p in points:
            if rising and p["CL"] <= rising[-1]["CL"]:
                break
            rising.append(p)
        res = _interp(rising, "CL", float(at_cl), ("aoa_deg", "CD", "L_over_D"))
        out["at_cl"] = {"CL": float(at_cl), **res}
    return out


__all__ = [
    "SWEEP_PATH",
    "build_sweep",
    "fit_lift_curve",
    "fit_polar",
    "lookup",
    "read_sweeps",
    "write_sweep_to_cpacs",
]
