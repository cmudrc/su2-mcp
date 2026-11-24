"""Run the gmsh mesher in a child process.

A hard failure inside gmsh then ends the child and not the server.

Found 2026-11-23: on one aircraft at ``surface_density`` 20, gmsh's Netgen
step failed ("Illegal hash-position", "Tetrahedron with unknown node") and
the next ``generate`` call took a segmentation fault inside libgmsh, not on
every run. The mesher ran inside the MCP server, so the server process ended
with it: the client saw "Connection closed" and every later tool failed. The
gateway's one-call CFD tool runs the same mesher inside the gateway process,
which in the container is process 1.

The child is this interpreter running the same mesher code on the real gmsh
(``cpacs_adapter._mesh_step_in_this_process``). It reports through a result
file; its log records and anything gmsh prints come back on one pipe. A child
that ends without a result file is reported as a failure with the exit status
and the last lines gmsh printed, and so is one that reports a mesh and then
ends abnormally. Nothing is retried here.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Records are logged under the adapter's name, as when the mesher ran in
#: the server process.
LOGGER = logging.getLogger("su2_mcp.cpacs_adapter")

#: Marks a line of the child's output that carries one log record.
_LOG_MARK = "SU2MCP-LOG "

#: Lines of the child's output kept for the error message.
_TAIL_LINES = 12
_TAIL_CHARS = 1500

_BOOTSTRAP = (
    "import sys; root = sys.argv[1]; "
    "root in sys.path or sys.path.insert(0, root); "
    "from su2_mcp.mesh_child import main; "
    "raise SystemExit(main(sys.argv[2:]))"
)


@dataclass
class MeshOutcome:
    """What the child reported, or how it ended without reporting."""

    ok: bool
    reason: str | None = None
    #: True when the child ended abnormally: gmsh took the process down.
    crashed: bool = False
    #: An exception the mesher raised in the child, as "Type: message".
    raised: str | None = None


def _child_command(
    step_path: str, su2_path: str, cfg_json: str, result_path: str
) -> list[str]:
    """Command line of the child.

    The folder this package was imported from is passed along, so the child
    runs the same code as the server that starts it.
    """
    root = str(Path(__file__).resolve().parents[1])
    return [
        sys.executable,
        "-c",
        _BOOTSTRAP,
        root,
        step_path,
        su2_path,
        cfg_json,
        result_path,
    ]


def describe_settings(cfg: dict[str, Any]) -> str:
    """Name the mesh settings of a run, for messages."""
    size = cfg.get("surface_size_m")
    near = (
        f"surface_size_m={size}"
        if size is not None
        else f"surface_density={cfg.get('surface_density', 30)}"
    )
    return f"{near}, farfield_factor={cfg.get('farfield_factor', 10.0)}"


def _describe_exit(returncode: int) -> str:
    if returncode < 0:
        try:
            return f"signal {signal.Signals(-returncode).name}"
        except ValueError:
            return f"signal {-returncode}"
    return f"exit code {returncode}"


def _crash_reason(returncode: int, cfg: dict[str, Any], tail: list[str]) -> str:
    printed = " | ".join(tail)[-_TAIL_CHARS:] if tail else "nothing"
    return (
        f"gmsh ended the meshing process ({_describe_exit(returncode)}) before a "
        f"mesh was written. Settings: {describe_settings(cfg)}. Last output: "
        f"{printed}. This is a failure inside gmsh for this geometry at this "
        "cell size; no mesh was attached and the server is still running. Try "
        "another surface_density or surface_size_m."
    )


def run_mesh_in_child(
    step_path: str, su2_path: str, mesh_cfg: dict[str, Any] | None = None
) -> MeshOutcome:
    """Mesh ``step_path`` into ``su2_path`` with gmsh in a child process."""
    cfg = dict(mesh_cfg or {})
    fd, result_path = tempfile.mkstemp(prefix="su2_mesh_result_", suffix=".json")
    os.close(fd)
    os.unlink(result_path)
    tail: collections.deque[str] = collections.deque(maxlen=_TAIL_LINES)
    proc = subprocess.Popen(
        _child_command(step_path, su2_path, json.dumps(cfg), result_path),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            if line.startswith(_LOG_MARK):
                try:
                    record = json.loads(line[len(_LOG_MARK) :])
                    level, text = int(record["level"]), str(record["message"])
                except (ValueError, KeyError, TypeError):
                    level, text = logging.INFO, line
                LOGGER.log(level, "%s", text)
                tail.append(text)
            else:
                # Printed by gmsh or Netgen themselves, past gmsh's own
                # terminal switch.
                LOGGER.info("gmsh: %s", line)
                tail.append(line)
        returncode = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    report: dict[str, Any] | None = None
    try:
        loaded = json.loads(Path(result_path).read_text(encoding="utf-8"))
        report = loaded if isinstance(loaded, dict) else None
    except (OSError, ValueError):
        report = None
    finally:
        Path(result_path).unlink(missing_ok=True)

    if report is None:
        # A partly written mesh is not a mesh.
        Path(su2_path).unlink(missing_ok=True)
        return MeshOutcome(
            ok=False, reason=_crash_reason(returncode, cfg, list(tail)), crashed=True
        )
    if returncode != 0 and report.get("ok"):
        # A mesh from a process that then ended abnormally is not trusted.
        Path(su2_path).unlink(missing_ok=True)
        return MeshOutcome(
            ok=False,
            reason=(
                f"gmsh wrote a mesh and its process then ended abnormally "
                f"({_describe_exit(returncode)}). Settings: "
                f"{describe_settings(cfg)}. The mesh was discarded and the "
                "server is still running. Try another surface_density or "
                "surface_size_m."
            ),
            crashed=True,
        )
    return MeshOutcome(
        ok=bool(report.get("ok")),
        reason=report.get("reason"),
        raised=report.get("raised"),
    )


class _LineHandler(logging.Handler):
    """Send each log record to the parent as one marked line."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.dumps(
                {"level": record.levelno, "message": record.getMessage()}
            )
            sys.stderr.write(f"{_LOG_MARK}{payload}\n")
            sys.stderr.flush()
        except Exception:  # pragma: no cover - logging must not end the run
            self.handleError(record)


def _exit_when_parent_goes() -> None:
    """End this process when the parent's end of standard input closes.

    The parent holds the pipe open for as long as it waits. If the server is
    stopped while a mesh is running, the mesher must not carry on alone.
    """

    def watch() -> None:
        # Read the descriptor itself: a thread waiting inside sys.stdin holds
        # its lock, and Python then aborts when the process exits normally.
        try:
            while os.read(0, 4096):
                pass
        except OSError:
            pass
        os._exit(70)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()


def main(argv: list[str]) -> int:
    """Child entry point: step path, mesh path, settings JSON, result path."""
    step_path, su2_path, cfg_json, result_path = argv
    _exit_when_parent_goes()
    root = logging.getLogger()
    root.handlers[:] = [_LineHandler()]
    root.setLevel(logging.DEBUG)

    from su2_mcp import cpacs_adapter as adapter

    report: dict[str, Any]
    try:
        adapter._LAST_MESH_FAILURE.clear()
        ok = adapter._mesh_step_in_this_process(
            step_path, su2_path, json.loads(cfg_json)
        )
        report = {"ok": bool(ok), "reason": adapter._LAST_MESH_FAILURE.get("reason")}
    except Exception as exc:
        report = {"ok": False, "raised": f"{type(exc).__name__}: {exc}"}
    partial = f"{result_path}.part"
    Path(partial).write_text(json.dumps(report), encoding="utf-8")
    os.replace(partial, result_path)
    return 0


__all__ = ["MeshOutcome", "describe_settings", "run_mesh_in_child"]
