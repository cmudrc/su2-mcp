"""Tests for configuration parsing helpers."""

from pathlib import Path

from su2_mcp_server import config_utils


def test_parse_and_update_round_trip(tmp_path: Path) -> None:
    """Config entries round-trip through parse and update helpers."""
    config_text = (
        "% comment\nMESH_FILENAME= mesh.su2\nCFL_NUMBER= 5.0\nMARKER_LIST= wall, farfield\n"
    )
    cfg_path = tmp_path / "config.cfg"
    cfg_path.write_text(config_text)

    parsed = config_utils.parse_config_file(cfg_path)
    assert parsed["CFL_NUMBER"] == 5.0
    assert parsed["MARKER_LIST"] == ["wall", "farfield"]

    updated_keys = config_utils.update_config_entries(
        cfg_path, {"CFL_NUMBER": 7, "NEW_KEY": True}, create_if_missing=True
    )
    assert set(updated_keys) == {"CFL_NUMBER", "NEW_KEY"}
    new_parsed = config_utils.parse_config_file(cfg_path)
    assert new_parsed["CFL_NUMBER"] == 7
    assert new_parsed["NEW_KEY"] is True
