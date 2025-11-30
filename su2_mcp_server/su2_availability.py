"""Utilities for discovering SU2 binaries on the host system."""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

DEFAULT_BINARIES: tuple[str, ...] = ("SU2_CFD", "SU2_CFD_MPI", "SU2_DEF")


@dataclass(frozen=True)
class SU2BinaryStatus:
    """Presence information for a single SU2 binary."""

    name: str
    path: str | None

    @property
    def available(self) -> bool:
        """Return True when the binary was found on PATH."""
        return self.path is not None


def discover_su2_binaries(candidates: Sequence[str] | None = None) -> list[SU2BinaryStatus]:
    """Locate SU2 binaries on the current PATH.

    Args:
        candidates: Optional iterable of binary names to probe. Defaults to
            common SU2 executables.

    Returns:
        Ordered list of binary status objects preserving the requested order.

    Examples:
        >>> discover_su2_binaries(["SU2_CFD"])  # doctest: +ELLIPSIS
        [SU2BinaryStatus(name='SU2_CFD', path=...)]

    """
    probe_targets: Iterable[str] = candidates if candidates is not None else DEFAULT_BINARIES
    return [SU2BinaryStatus(name=target, path=shutil.which(target)) for target in probe_targets]


def summarize_binaries(statuses: Sequence[SU2BinaryStatus]) -> dict[str, object]:
    """Convert binary statuses into a serializable summary."""
    missing = [status.name for status in statuses if not status.available]
    return {
        "installed": any(status.available for status in statuses),
        "binaries": [
            {"name": status.name, "path": status.path, "available": status.available}
            for status in statuses
        ],
        "missing": missing,
    }


def check_su2_installation(candidates: Sequence[str] | None = None) -> dict[str, object]:
    """Report SU2 availability on the host system.

    Args:
        candidates: Optional list of binary names to probe; defaults to common
            SU2 executables.

    Returns:
        Mapping describing which binaries are present and whether any are
        missing. The ``installed`` flag is true when at least one binary is
        present.

    Examples:
        >>> summary = check_su2_installation(["SU2_CFD"])
        >>> set(summary.keys()) == {"installed", "binaries", "missing"}
        True

    """
    statuses = discover_su2_binaries(candidates)
    return summarize_binaries(statuses)


__all__ = [
    "DEFAULT_BINARIES",
    "SU2BinaryStatus",
    "check_su2_installation",
    "discover_su2_binaries",
    "summarize_binaries",
]
