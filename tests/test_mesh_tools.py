"""Coverage for STEP-to-mesh tool behavior under deterministic mocks."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from su2_mcp.tools import mesh_tools, session

VALID_STEP_B64 = base64.b64encode(b"ISO-10303-21;\nENDSEC;\n").decode("utf-8")


def test_default_geo_content_is_loaded() -> None:
    """Bundled .geo template should be loadable from package resources."""
    content = mesh_tools._default_geo_content()
    assert "FARFIELD" in content


def test_generate_mesh_from_step_invalid_session() -> None:
    """Unknown sessions should return not_found immediately."""
    result = mesh_tools.generate_mesh_from_step("missing", VALID_STEP_B64)
    assert result["error"]["type"] == "not_found"


def test_generate_mesh_from_step_missing_gmsh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing gmsh binary should return a missing_dependency error."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: None)

    result = mesh_tools.generate_mesh_from_step(session_id, VALID_STEP_B64)
    assert result["error"]["type"] == "missing_dependency"

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_mesh_from_step_rejects_invalid_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed base64 payloads should return a validation-style error."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: "/usr/bin/gmsh")

    result = mesh_tools.generate_mesh_from_step(session_id, "not-base64")
    assert result["error"]["message"] == "Invalid step_base64"

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_mesh_from_step_rejects_non_step_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STEP bytes must start with the expected ISO-10303-21 marker."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    bad_b64 = base64.b64encode(b"not-a-step").decode("utf-8")
    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: "/usr/bin/gmsh")

    result = mesh_tools.generate_mesh_from_step(session_id, bad_b64)
    assert result["error"]["type"] == "validation_error"

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_mesh_from_step_rejects_missing_geo_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom template paths must point to existing files."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: "/usr/bin/gmsh")

    result = mesh_tools.generate_mesh_from_step(
        session_id,
        VALID_STEP_B64,
        geo_template_path="/tmp/does-not-exist.geo",
    )
    assert result["error"]["type"] == "validation_error"

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_mesh_from_step_gmsh_failure_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-zero gmsh exits should return stderr/stdout diagnostics."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    geo = tmp_path / "mesh.geo"
    geo.write_text('SetFactory("OpenCASCADE");\n', encoding="utf-8")

    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: "/usr/bin/gmsh")

    def _fake_run(
        cmd: list[str],
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: int,
    ) -> SimpleNamespace:
        del cmd, cwd, capture_output, text, timeout
        return SimpleNamespace(returncode=2, stdout="bad", stderr="worse")

    monkeypatch.setattr(mesh_tools.subprocess, "run", _fake_run)

    result = mesh_tools.generate_mesh_from_step(
        session_id,
        VALID_STEP_B64,
        geo_template_path=str(geo),
    )
    assert result["error"]["message"] == "gmsh failed"
    assert result["error"]["details"]["returncode"] == 2

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_mesh_from_step_gmsh_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Gmsh timeout exceptions should map to timeout errors."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    geo = tmp_path / "mesh.geo"
    geo.write_text('SetFactory("OpenCASCADE");\n', encoding="utf-8")

    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: "/usr/bin/gmsh")

    def _fake_run(
        cmd: list[str],
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: int,
    ) -> SimpleNamespace:
        del cwd, capture_output, text
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(mesh_tools.subprocess, "run", _fake_run)

    result = mesh_tools.generate_mesh_from_step(
        session_id,
        VALID_STEP_B64,
        geo_template_path=str(geo),
        gmsh_timeout_seconds=3,
    )
    assert result["error"]["type"] == "timeout"

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_mesh_from_step_missing_output_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful exit without output should produce runtime_error."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    geo = tmp_path / "mesh.geo"
    geo.write_text('SetFactory("OpenCASCADE");\n', encoding="utf-8")

    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: "/usr/bin/gmsh")

    def _fake_run(
        cmd: list[str],
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: int,
    ) -> SimpleNamespace:
        del cmd, cwd, capture_output, text, timeout
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_tools.subprocess, "run", _fake_run)

    result = mesh_tools.generate_mesh_from_step(
        session_id,
        VALID_STEP_B64,
        geo_template_path=str(geo),
    )
    assert result["error"]["type"] == "runtime_error"

    session.close_su2_session(session_id, delete_workdir=True)


def test_generate_mesh_from_step_success_updates_session_mesh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Successful gmsh runs should write mesh bytes into the target session."""
    created = session.create_su2_session()
    session_id = str(created["session_id"])

    geo = tmp_path / "mesh.geo"
    geo.write_text('SetFactory("OpenCASCADE");\n', encoding="utf-8")

    monkeypatch.setattr(mesh_tools.shutil, "which", lambda _name: "/usr/bin/gmsh")

    temp_workdir = tmp_path / "temp_work"

    def _fake_mkdtemp(prefix: str) -> str:
        del prefix
        temp_workdir.mkdir(parents=True, exist_ok=True)
        return str(temp_workdir)

    monkeypatch.setattr(mesh_tools.tempfile, "mkdtemp", _fake_mkdtemp)

    def _fake_run(
        cmd: list[str],
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: int,
    ) -> SimpleNamespace:
        del cwd, capture_output, text, timeout
        out_mesh = Path(cmd[cmd.index("-o") + 1])
        out_mesh.write_bytes(b"NDIME= 3\nNPOIN= 0\nNELEM= 0\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mesh_tools.subprocess, "run", _fake_run)

    result = mesh_tools.generate_mesh_from_step(
        session_id,
        VALID_STEP_B64,
        output_mesh_name="generated.su2",
        geo_template_path=str(geo),
    )

    assert result["success"] is True
    assert result["mesh_size_bytes"] > 0

    info = session.get_session_info(session_id)
    mesh_path = Path(str(info["mesh_path"]))
    assert mesh_path.name == "generated.su2"
    assert mesh_path.exists()
    assert not temp_workdir.exists()

    session.close_su2_session(session_id, delete_workdir=True)
