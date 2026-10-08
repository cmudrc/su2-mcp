"""Session management utilities for SU2 MCP server."""

from __future__ import annotations

import base64
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from su2_mcp.config_seed import seed_config_text


@dataclass
class LastRunMetadata:
    """Metadata captured after running a SU2 solver."""

    solver: str
    config_used: str
    exit_code: int
    runtime_seconds: float
    log_tail: str


@dataclass
class SessionRecord:
    """Session state stored by :class:`SessionManager`."""

    session_id: str
    workdir: Path
    config_path: Path
    mesh_path: Path | None = None
    last_run_metadata: LastRunMetadata | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


def _decode_base64_content(value: str, param: str) -> bytes:
    """Decode a base64 *content* argument, refusing values that are clearly
    file names, paths or URIs.

    Found 2026-09-30 in a colleague's integration: a small planner passed
    "mesh.su2" as initial_mesh and a file:// URI as STEP content, and the
    only message back was base64's "Incorrect padding", which says nothing
    about what the argument takes.
    """
    text = value.strip()
    looks_like_path = (
        text.startswith(("file://", "./", "../", "/", "~"))
        or ("/" in text and " " not in text and len(text) < 512)
        or (len(text) < 128 and "." in text and not text.endswith("="))
    )
    try:
        return base64.b64decode(text, validate=True)
    except Exception as exc:
        hint = (
            f"{param} takes the base64-encoded file CONTENT, not a file name "
            "or path. Read the file and base64-encode its bytes, or pass the "
            "*_base64 field another tool returned (for STEP geometry, the "
            "cad_base64 field from tigl export_configuration_cad)."
        )
        if looks_like_path:
            hint = (
                f"{param} looks like a file name, path or URI ({text[:80]!r}), "
                "but it " + hint.split(param + " ", 1)[1]
            )
        raise ValueError(hint) from exc


def _require_su2_mesh_bytes(data: bytes, param: str) -> None:
    """A mesh argument must actually be an SU2 mesh.

    2026-10-02: a model-driven client passed STEP geometry bytes as
    initial_mesh; they decode as valid base64, so the session happily held a
    CAD file named mesh.su2 and the solver would later refuse it cryptically.
    SU2 ASCII meshes start with an NDIME declaration; anything else is
    refused here with the fix named.
    """
    head = data.lstrip()[:16]
    if not head.startswith(b"NDIME"):
        kind = "STEP geometry" if data.lstrip().startswith(b"ISO-10303-21") else "not an SU2 mesh"
        raise ValueError(
            f"{param} must be base64 of an SU2 mesh file (starts with "
            f"'NDIME='); got {kind}. To mesh STEP geometry, call "
            "generate_mesh_from_step with it instead."
        )


class SessionManager:
    """Manage SU2 sessions and their resources."""

    def __init__(self) -> None:
        """Create an empty session registry."""
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        base_name: str | None = None,
        initial_config: str | None = None,
        initial_mesh: str | None = None,
        mesh_file_name: str = "mesh.su2",
    ) -> SessionRecord:
        """Create a new SU2 session with optional seed files."""
        session_id = str(uuid.uuid4())
        prefix = f"su2_{base_name}_" if base_name else "su2_session_"
        workdir = Path(tempfile.mkdtemp(prefix=prefix))
        config_path = workdir / "config.cfg"

        config_text = initial_config or seed_config_text(mesh_file_name)
        config_path.write_text(config_text)

        mesh_path: Path | None = None
        if initial_mesh is not None:
            mesh_bytes = _decode_base64_content(initial_mesh, "initial_mesh")
            _require_su2_mesh_bytes(mesh_bytes, "initial_mesh")
            mesh_path = workdir / mesh_file_name
            mesh_path.write_bytes(mesh_bytes)
            self._ensure_mesh_filename_in_config(config_path, mesh_file_name)

        record = SessionRecord(
            session_id=session_id,
            workdir=workdir,
            config_path=config_path,
            mesh_path=mesh_path,
        )

        with self._lock:
            self._sessions[session_id] = record

        return record

    def _ensure_mesh_filename_in_config(
        self, config_path: Path, mesh_file_name: str
    ) -> None:
        """Ensure the configuration declares the mesh filename."""
        existing = config_path.read_text().splitlines()
        updated = []
        mesh_key_written = False
        for line in existing:
            if line.strip().startswith("MESH_FILENAME"):
                updated.append(f"MESH_FILENAME= {mesh_file_name}")
                mesh_key_written = True
            else:
                updated.append(line)
        if not mesh_key_written:
            updated.append(f"MESH_FILENAME= {mesh_file_name}")
        config_path.write_text("\n".join(updated) + "\n")

    def close_session(self, session_id: str, delete_workdir: bool = False) -> bool:
        """Close a session and optionally remove its working directory."""
        with self._lock:
            record = self._sessions.pop(session_id, None)
        if record is None:
            return False
        if delete_workdir:
            shutil.rmtree(record.workdir, ignore_errors=True)
        return True

    def get(self, session_id: str) -> SessionRecord | None:
        """Return the session record if it exists."""
        with self._lock:
            return self._sessions.get(session_id)

    def require(self, session_id: str) -> SessionRecord:
        """Return the session record or raise if missing."""
        record = self.get(session_id)
        if record is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return record

    def update_mesh(
        self,
        session_id: str,
        mesh_base64: str,
        mesh_file_name: str = "mesh.su2",
    ) -> Path:
        """Persist a mesh to the session directory and update bookkeeping."""
        record = self.require(session_id)
        mesh_bytes = _decode_base64_content(mesh_base64, "mesh_base64")
        _require_su2_mesh_bytes(mesh_bytes, "mesh_base64")
        mesh_path = record.workdir / mesh_file_name
        mesh_path.write_bytes(mesh_bytes)
        record.mesh_path = mesh_path
        self._ensure_mesh_filename_in_config(record.config_path, mesh_file_name)
        return mesh_path

    def to_info(self, session_id: str) -> dict[str, object]:
        """Return a JSON-friendly description of the session."""
        record = self.require(session_id)
        return {
            "session_id": record.session_id,
            "workdir": str(record.workdir),
            "config_path": str(record.config_path),
            "mesh_path": str(record.mesh_path) if record.mesh_path else None,
            "last_run": (
                None
                if record.last_run_metadata is None
                else {
                    "solver": record.last_run_metadata.solver,
                    "config_used": record.last_run_metadata.config_used,
                    "exit_code": record.last_run_metadata.exit_code,
                    "runtime_seconds": record.last_run_metadata.runtime_seconds,
                    "log_tail": record.last_run_metadata.log_tail,
                }
            ),
        }

    def record_run(self, session_id: str, metadata: LastRunMetadata) -> None:
        """Store the last run metadata for the session."""
        record = self.require(session_id)
        record.last_run_metadata = metadata
