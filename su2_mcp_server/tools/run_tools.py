"""Tools that execute SU2 solvers."""

from __future__ import annotations

from su2_mcp_server.su2_runner import SU2Runner, build_last_run_metadata
from su2_mcp_server.tools.session import SESSION_MANAGER, _error


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
) -> dict[str, object]:
    """Run a SU2 solver process and capture output metadata."""
    try:
        record = SESSION_MANAGER.require(session_id)
        config_path = (
            record.workdir / config_override_path if config_override_path else record.config_path
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
        config_path = record.workdir / def_config_path if def_config_path else record.config_path
        runner = SU2Runner(record.workdir)
        result = runner.run("SU2_DEF", config_path, max_runtime_seconds, capture_log_lines=200)
        success = bool(result.get("success"))
        result_payload: dict[str, object] = {
            "success": success,
            "exit_code": _as_int(result.get("exit_code", -1)),
            "runtime_seconds": _as_float(result.get("runtime_seconds", 0.0)),
            "log_tail": str(result.get("log_tail", "")),
            "deformed_mesh_path": str(record.workdir / output_mesh_name) if success else None,
        }
        if "error" in result:
            result_payload["error"] = result["error"]
        return result_payload
    except KeyError as exc:
        return _error(str(exc), error_type="not_found")
    except Exception as exc:  # pragma: no cover
        return _error("Failed to generate deformed mesh", details=str(exc))


__all__ = ["run_su2_solver", "generate_deformed_mesh"]
