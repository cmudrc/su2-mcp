"""Checks for packaging metadata and repository developer-contract files."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict[str, object]:
    """Load and parse the repository pyproject file."""
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_project_urls_and_cli_entrypoint_are_declared() -> None:
    """Package metadata exposes required URLs, python floor, and CLI script."""
    project = _pyproject()["project"]

    assert project["requires-python"] == ">=3.12"
    assert project["scripts"]["su2-mcp"] == "su2_mcp.main:main"
    assert "Documentation" in project["urls"]
    assert "Repository" in project["urls"]
    assert "Issues" in project["urls"]


def test_dev_dependencies_include_docs_and_release_tooling() -> None:
    """The dev extra includes docs/build/publish/pre-commit tooling."""
    dev_dependencies = _pyproject()["project"]["optional-dependencies"]["dev"]

    assert any(dep.startswith("sphinx") for dep in dev_dependencies)
    assert any(dep.startswith("build") for dep in dev_dependencies)
    assert any(dep.startswith("twine") for dep in dev_dependencies)
    assert any(dep.startswith("pre-commit") for dep in dev_dependencies)


def test_src_layout_and_makefile_targets_are_declared() -> None:
    """The repo uses src layout and includes expected Makefile workflow targets."""
    config = _pyproject()

    assert config["tool"]["setuptools"]["package-dir"][""] == "src"
    assert "src" in config["tool"]["setuptools"]["packages"]["find"]["where"]

    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in [
        "dev:",
        "install-dev:",
        "lint:",
        "fmt:",
        "fmt-check:",
        "type:",
        "test:",
        "qa:",
        "coverage:",
        "examples-smoke:",
        "examples-test:",
        "docs-build:",
        "docs-check:",
        "docs-linkcheck:",
        "release-check:",
        "ci:",
        "clean:",
    ]:
        assert target in makefile


def test_su2_optional_extra_is_preserved() -> None:
    """The optional `su2` extra remains available for environments with SU2."""
    optional = _pyproject()["project"]["optional-dependencies"]
    assert "su2" in optional
    assert "SU2" in optional["su2"]


def test_coverage_gate_default_is_meaningful() -> None:
    """Coverage threshold script should enforce a high default minimum."""
    script = (REPO_ROOT / "scripts" / "check_coverage_thresholds.py").read_text(
        encoding="utf-8"
    )
    assert "DEFAULT_MINIMUM = 90.0" in script
