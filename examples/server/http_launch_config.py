"""Show a non-blocking HTTP transport configuration parse for the CLI."""

from __future__ import annotations

import json

from su2_mcp.main import build_parser


def main() -> None:
    """Parse sample HTTP arguments and print the resulting configuration."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--path",
            "/mcp",
        ]
    )
    payload = {
        "transport": args.transport,
        "host": args.host,
        "port": args.port,
        "path": args.path,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
