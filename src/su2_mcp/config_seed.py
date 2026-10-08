"""The configuration a raw SU2 session starts from.

Until 2026-10-08 a session created without `initial_config` held two lines
(a comment and MESH_FILENAME). Two of three model-driven runs that day wrote
their own configuration from that start and left out MARKER_MONITORING, so
SU2 evaluated the force coefficients on no surface and wrote CL = CD = 0.0
for every iteration; the third chose its own scheme, CFL and iteration count
and reported an unconverged result. The seed below is the numerics block of
the preset path (`cpacs_adapter._write_euler_config`, laptop preset) with
the case-specific values left unset: MACH_NUMBER, AOA and REF_AREA must be
set with `su2_update_config_entries` before `su2_run_su2_solver` will run.
Nothing here is a flight condition or a reference value.
"""

from __future__ import annotations

from su2_mcp.cpacs_adapter import MESH_PRESETS, resolve_preset

#: Keys `su2_run_su2_solver` requires before it will launch SU2_CFD.
#: MARKER_MONITORING: without it SU2 reports CL = CD = 0.0 (no surface).
#: MACH_NUMBER, AOA: the flight condition; SU2's own defaults are not a case.
#: REF_AREA: SU2 silently normalises by 1.0 m^2 when it is absent.
REQUIRED_FOR_SU2_CFD: tuple[str, ...] = (
    "MARKER_MONITORING",
    "MACH_NUMBER",
    "AOA",
    "REF_AREA",
)

#: Values that mean "no marker" in an SU2 configuration (spaces removed).
_EMPTY_MARKER_VALUES = {"", "NONE", "()"}


def seed_config_text(
    mesh_file_name: str = "mesh.su2", preset: str | None = None
) -> str:
    """Return the configuration text a new raw session starts with.

    Numerics, markers, convergence cap and output fields are those of the
    preset path (`laptop` unless `preset` names another entry of
    `MESH_PRESETS`). The case-specific keys are present only as comments.
    """
    p = resolve_preset(preset)
    iter_cap = int(p["iter"])
    label = str(p.get("label", preset or "laptop"))
    return f"""\
% SU2 configuration seeded by su2-mcp from the '{label}' preset.
% Set the case before running (su2_update_config_entries):
%   MACH_NUMBER=  (required)
%   AOA=          (required, degrees)
%   REF_AREA=     (required, m^2; the CPACS reference area)
%   REF_LENGTH=   (optional, m; moments only)
% su2_run_su2_solver refuses to run until the required keys are set.
% Forces are evaluated only on MARKER_MONITORING; keep it as the wall marker.

% ----------- SOLVER -----------%
SOLVER= EULER
MATH_PROBLEM= DIRECT

% ----------- FREESTREAM -----------%
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= 101325.0
FREESTREAM_TEMPERATURE= 288.15
REF_DIMENSIONALIZATION= DIMENSIONAL

% ----------- MESH -----------%
MESH_FILENAME= {mesh_file_name}
MESH_FORMAT= SU2

% ----------- BOUNDARY CONDITIONS (as the mesher names them) -----------%
MARKER_FAR= ( FARFIELD )
MARKER_EULER= ( WALL )
MARKER_PLOTTING= ( WALL )
MARKER_MONITORING= ( WALL )

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
CONV_RESIDUAL_MINVAL= -10

% ----------- OUTPUT -----------%
OUTPUT_FILES= ( RESTART, PARAVIEW )
OUTPUT_WRT_FREQ= 50
CONV_FILENAME= history
HISTORY_OUTPUT= ( ITER, RMS_RES, LIFT, DRAG, AERO_COEFF )
SCREEN_OUTPUT= INNER_ITER, RMS_DENSITY, RMS_MOMENTUM-X, RMS_ENERGY, LIFT, DRAG
"""


def missing_required_keys(entries: dict[str, object]) -> list[str]:
    """Keys of `REQUIRED_FOR_SU2_CFD` absent or empty in parsed config entries."""
    missing: list[str] = []
    for key in REQUIRED_FOR_SU2_CFD:
        value = entries.get(key)
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, list):
            text = ",".join(str(v) for v in value)
        else:
            text = str(value)
        compact = text.replace(" ", "").upper()
        if compact in _EMPTY_MARKER_VALUES:
            missing.append(key)
    return missing


__all__ = [
    "REQUIRED_FOR_SU2_CFD",
    "MESH_PRESETS",
    "seed_config_text",
    "missing_required_keys",
]
