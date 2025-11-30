"""Tests for packaging metadata related to optional extras."""

from __future__ import annotations

import tomllib
from typing import cast


def test_su2_extra_declared() -> None:
    """The optional dependency group 'su2' should install the SU2 package."""
    with open("pyproject.toml", "rb") as pyproject_file:
        config = tomllib.load(pyproject_file)

    project = config.get("project", {})
    optional_dependencies = cast(dict[str, list[str]], project.get("optional-dependencies", {}))

    assert "su2" in optional_dependencies
    assert "SU2" in optional_dependencies["su2"]
