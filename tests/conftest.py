"""Shared test fixtures."""

from __future__ import annotations

import base64

import pytest


@pytest.fixture()
def sample_config_text() -> str:
    """Provide a small SU2 config payload for deterministic tests."""
    return (
        "% comment\n"
        "MESH_FILENAME= mesh.su2\n"
        "CFL_NUMBER= 5.0\n"
        "MARKER_LIST= wall, farfield\n"
    )


@pytest.fixture()
def sample_mesh_base64() -> str:
    """Provide a deterministic mesh-like payload encoded as base64."""
    return base64.b64encode(b"NDIME= 3\nNPOIN= 0\nNELEM= 0\n").decode("utf-8")
