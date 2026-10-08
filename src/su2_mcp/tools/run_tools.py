"""Tools that execute SU2 solvers."""

from __future__ import annotations

from su2_mcp.config_seed import REQUIRED_FOR_SU2_CFD, missing_required_keys
from su2_mcp.config_utils import parse_config_file
from su2_mcp.su2_runner import SU2Runner, build_last_run_metadata
from su2_mcp.tools.session import SESSION_MANAGER, _error


def _as_int(value: object, default: int = -1) -> int:
    if isinstance(value, (int, float, str)):
        return int(value)
    return default


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float, str)):
        return float(value)
    return default


def run_su2_solver(
    session_id: str,
    solver: str = "SU2_CFD",
    config_override_path: str | None = None,
    max_runtime_seconds: int = 600,
    capture_log_lines: int = 100,
    allow_incomplete_config: bool = False,
) -> dict[str, object]:
    """Run a SU2 solver process and capture output metadata.

    For SU2_CFD the configuration must set MARKER_MONITORING, MACH_NUMBER,
    AOA and REF_AREA; otherwise the tool returns an error of type
    `config_incomplete` and runs nothing. Without MARKER_MONITORING SU2
    evaluates the force coefficients on no surface and writes CL = CD = 0.0
    (two model-driven runs on 2026-10-08); without the other three it runs a
    case nobody specified. `allow_incomplete_config=True` skips the check for
    runs that want no force coefficients.
    """
    # 2026-10-02, model-driven client: passed the config's physics value
    # ("EULER") as the binary name. `solver` is the executable to launch;
    # the physics lives in the config's SOLVER field.
    known = ("SU2_CFD", "SU2_CFD_MPI", "SU2_DEF", "SU2_DOT", "SU2_SOL")
    if solver not in known:
        return _error(
            f"solver={solver!r} is not an SU2 binary name. This argument "
            f"names the executable to run (one of {', '.join(known)}; "
            "default SU2_CFD). The physics model (EULER, RANS, ...) is set "
            "by the SOLVER field inside the session's config file.",
            error_type="invalid_input",
        )
    try:
        record = SESSION_MANAGER.require(session_id)
        config_path = (
            record.workdir / config_override_path
            if config_override_path
            else record.config_path
        )
        if (
            solver in ("SU2_CFD", "SU2_CFD_MPI")
            and not allow_incomplete_config
            and config_path.exists()
        ):
            missing = missing_required_keys(parse_config_file(config_path))
            if missing:
                return _error(
                    "The configuration is incomplete for a force-coefficient run: "
                    + ", ".join(missing)
                    + " not set. Without MARKER_MONITORING SU2 evaluates CL and CD "
                    "on no surface and writes 0.0 for every iteration; without "
                    "MACH_NUMBER and AOA no flight condition was specified; "
                    "without REF_AREA SU2 normalises by 1.0 m^2. Set them with "
                    "su2_update_config_entries (MARKER_MONITORING= ( WALL ) for "
                    "meshes from su2_generate_mesh_from_step), or call su2_run_aero "
                    "for the validated preset setup. Nothing was run.",
                    error_type="config_incomplete",
                    details={
                        "missing": missing,
                        "required": list(REQUIRED_FOR_SU2_CFD),
                        "config_path": str(config_path),
                    },
                )
        runner = SU2Runner(record.workdir)
        result = runner.run(solver, config_path, max_runtime_seconds, capture_log_lines)
        if "error" not in result:
            metadata = build_last_run_metadata(result)
            SESSION_MANAGER.record_run(session_id, metadata)
        return result
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to run solver", details=str(exc))


def generate_deformed_mesh(
    session_id: str,
    def_config_path: str | None = None,
    output_mesh_name: str = "mesh_def.su2",
    max_runtime_seconds: int = 600,
) -> dict[str, object]:
    """Run SU2_DEF to create a deformed mesh."""
    try:
        record = SESSION_MANAGER.require(session_id)
        config_path = (
            record.workdir / def_config_path if def_config_path else record.config_path
        )
        runner = SU2Runner(record.workdir)
        result = runner.run(
            "SU2_DEF", config_path, max_runtime_seconds, capture_log_lines=200
        )
        success = bool(result.get("success"))
        result_payload: dict[str, object] = {
            "success": success,
            "exit_code": _as_int(result.get("exit_code", -1)),
            "runtime_seconds": _as_float(result.get("runtime_seconds", 0.0)),
            "log_tail": str(result.get("log_tail", "")),
            "deformed_mesh_path": str(record.workdir / output_mesh_name)
            if success
            else None,
        }
        if "error" in result:
            result_payload["error"] = result["error"]
        return result_payload
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to generate deformed mesh", details=str(exc))


__all__ = ["run_su2_solver", "generate_deformed_mesh"]
