"""Utilities for parsing and modifying SU2 configuration files."""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from pathlib import Path


def _infer_scalar(value: str) -> object:
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def parse_config_text(config_text: str) -> dict[str, object]:
    """Parse SU2 configuration text into a dictionary."""
    entries: dict[str, object] = {}
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%") or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", maxsplit=1)]
        if not key:
            continue
        if "," in value:
            parts = [segment.strip() for segment in value.split(",") if segment.strip()]
            entries[key] = [_infer_scalar(part) for part in parts]
        else:
            entries[key] = _infer_scalar(value)
    return entries


def parse_config_file(config_path: Path) -> dict[str, object]:
    """Parse a configuration file from disk."""
    return parse_config_text(config_path.read_text())


def _format_value(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_value(item) for item in value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def update_config_entries(
    config_path: Path,
    updates: MutableMapping[str, object],
    create_if_missing: bool = True,
) -> list[str]:
    """Update configuration entries and persist them to disk."""
    entries = parse_config_file(config_path)
    updated_keys: list[str] = []

    for key, value in updates.items():
        if key in entries or create_if_missing:
            entries[key] = value
            updated_keys.append(key)

    serialized_lines = _serialize_entries(entries.items())
    config_path.write_text("\n".join(serialized_lines) + "\n")
    return updated_keys


def _serialize_entries(entries: Iterable[tuple[str, object]]) -> list[str]:
    return [f"{key}= {_format_value(value)}" for key, value in entries]
