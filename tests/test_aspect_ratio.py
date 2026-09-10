"""The CD0/CDi split must use a real aspect ratio, never area / length.

Found 2026-09-10: the adapter divided the CPACS reference area by the reference
length and used the quotient as the aspect ratio. For the D150 that is 29.1
against a real 9.4, which understated induced drag about 3x, and the induced
drag factor published in the paper (k = 0.0129) was exactly this formula with
that quotient in it.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from su2_mcp.cpacs_adapter import _wing_aspect_ratio, read_from_cpacs


def _cpacs(
    area: str | None = "122.4",
    positionings: bool = True,
    symmetry: bool = True,
    ar_node: str | None = None,
) -> str:
    ref = (
        f"<reference>{'<area>' + area + '</area>' if area else ''}<length>4.2</length>"
    )
    ref += (f"<aspectRatio>{ar_node}</aspectRatio>" if ar_node else "") + "</reference>"
    pos = ""
    if positionings:
        rows = [
            ("p1", 0, 0, 0),
            ("p2", 1.875, 0, 0),
            ("p3", 5.05, 25, 5),
            ("p4", 12.013, 25, 5),
        ]
        pos = (
            "<positionings>"
            + "".join(
                f"<positioning uID='{u}'><length>{L}</length>"
                f"<sweepAngle>{sw}</sweepAngle>"
                f"<dihedralAngle>{d}</dihedralAngle></positioning>"
                for u, L, sw, d in rows
            )
            + "</positionings>"
        )
    sym = " symmetry='x-z-plane'" if symmetry else ""
    return (
        "<cpacs><vehicles><aircraft><model uID='m'>"
        + ref
        + f"<wings><wing uID='w'{sym}><name>main</name>{pos}</wing></wings>"
        "</model></aircraft></vehicles></cpacs>"
    )


def _expected_ar() -> float:
    half = 1.875 + (5.05 + 12.013) * math.cos(math.radians(25)) * math.cos(
        math.radians(5)
    )
    return (2 * half) ** 2 / 122.4


def test_aspect_ratio_comes_from_wing_positionings() -> None:
    inputs = read_from_cpacs(_cpacs())
    assert inputs["aspect_ratio"] == pytest.approx(
        _expected_ar(), abs=6e-4
    )  # adapter rounds to 3 dp
    assert "positionings" in inputs["aspect_ratio_source"]


def test_aspect_ratio_is_never_area_over_length() -> None:
    inputs = read_from_cpacs(_cpacs())
    assert inputs["aspect_ratio"] != pytest.approx(122.4 / 4.2, rel=0.05)
    assert 8.0 < inputs["aspect_ratio"] < 11.0


def test_explicit_reference_aspect_ratio_wins() -> None:
    inputs = read_from_cpacs(_cpacs(ar_node="9.5"))
    assert inputs["aspect_ratio"] == 9.5
    assert inputs["aspect_ratio_source"] == "cpacs:reference/aspectRatio"


def test_no_reference_area_means_no_aspect_ratio_not_a_guess() -> None:
    inputs = read_from_cpacs(_cpacs(area=None))
    assert inputs["aspect_ratio"] is None
    assert "no reference area" in inputs["aspect_ratio_source"]


def test_no_positionings_means_no_aspect_ratio_not_a_guess() -> None:
    inputs = read_from_cpacs(_cpacs(positionings=False))
    assert inputs["aspect_ratio"] is None
    assert "no wing positionings" in inputs["aspect_ratio_source"]


def test_asymmetric_wing_is_not_doubled() -> None:
    root = ET.fromstring(_cpacs(symmetry=False))
    ar, _ = _wing_aspect_ratio(root, 122.4)
    assert ar == pytest.approx(_expected_ar() / 4.0, abs=6e-4)
