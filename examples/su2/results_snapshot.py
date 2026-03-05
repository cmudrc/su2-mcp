"""Create deterministic result files and inspect them through tools."""

from __future__ import annotations

import base64
import json

from su2_mcp.tools import (
    close_su2_session,
    create_su2_session,
    results_tools,
    session,
)


def main() -> None:
    """Write sample results, query them, and print a stable JSON snapshot."""
    created = create_su2_session(base_name="results")
    session_id = str(created["session_id"])
    record = session.SESSION_MANAGER.require(session_id)

    history_path = record.workdir / "history.csv"
    history_path.write_text("iter,residual\n1,0.1\n2,0.01\n", encoding="utf-8")

    listing = results_tools.list_result_files(session_id, extensions=[".csv"])
    history = results_tools.read_history_csv(session_id, "history.csv")
    encoded = results_tools.get_result_file_base64(
        session_id, "history.csv", max_bytes=12
    )

    close_su2_session(session_id, delete_workdir=True)

    rows = history.get("rows", [])
    first_row = rows[0] if rows else {}
    decoded_prefix = base64.b64decode(str(encoded.get("data_base64", ""))).decode(
        "utf-8", errors="ignore"
    )
    payload = {
        "file_count": len(listing.get("files", [])),
        "first_residual": first_row.get("residual"),
        "truncated": encoded.get("truncated"),
        "data_prefix": decoded_prefix,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
