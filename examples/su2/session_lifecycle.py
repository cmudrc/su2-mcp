"""Create a session, inspect config metadata, and close it."""

from __future__ import annotations

import json

from su2_mcp.tools import (
    close_su2_session,
    create_su2_session,
    get_session_info,
    parse_config,
)


def main() -> None:
    """Run the deterministic session lifecycle and print a JSON summary."""
    created = create_su2_session(base_name="example")
    session_id = str(created["session_id"])

    info = get_session_info(session_id)
    parsed = parse_config(session_id)
    close_result = close_su2_session(session_id, delete_workdir=True)

    payload = {
        "session_opened": "error" not in created,
        "session_closed": close_result.get("success", False),
        "mesh_path": info.get("mesh_path"),
        "config_keys": sorted(parsed.get("entries", {}).keys()),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
