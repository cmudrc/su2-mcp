"""CLI contract tests for SU2 MCP server entrypoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import su2_mcp.main as server_main


class _DummyApp:
    """FastMCP shim that captures run invocations for CLI assertions."""

    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            host="127.0.0.1",
            port=8000,
            mount_path="/",
            sse_path="/sse",
            message_path="/messages/",
            streamable_http_path="/mcp",
            json_response=False,
            stateless_http=False,
        )
        self.run_calls: list[dict[str, object]] = []

    def run(self, *, transport: str, mount_path: str | None = None) -> None:
        """Capture transport arguments passed by the CLI."""
        self.run_calls.append({"transport": transport, "mount_path": mount_path})


def test_build_parser_defaults_to_stdio_transport() -> None:
    """The CLI defaults to stdio with expected baseline host/port/path values."""
    parser = server_main.build_parser()
    args = parser.parse_args([])

    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.path == "/mcp"
    assert args.streamable_http_path == "/mcp"


def test_main_maps_http_alias_to_streamable_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--transport http` maps to streamable-http using `--path`."""
    dummy_app = _DummyApp()
    create_kwargs: dict[str, object] = {}

    def _fake_create_app(**kwargs: object) -> _DummyApp:
        create_kwargs.update(kwargs)
        return dummy_app

    monkeypatch.setattr(server_main, "create_app", _fake_create_app)

    exit_code = server_main.main(
        [
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
            "--path",
            "/custom",
        ]
    )

    assert exit_code == 0
    assert create_kwargs["host"] == "0.0.0.0"
    assert create_kwargs["port"] == 9001
    assert create_kwargs["streamable_http_path"] == "/custom"
    assert dummy_app.run_calls == [{"transport": "streamable-http", "mount_path": None}]


def test_main_runs_sse_with_mount_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSE transport forwards the configured mount path to run()."""
    dummy_app = _DummyApp()
    monkeypatch.setattr(server_main, "create_app", lambda **_kwargs: dummy_app)

    exit_code = server_main.main(
        ["--transport", "sse", "--mount-path", "/api", "--sse-path", "/events"]
    )

    assert exit_code == 0
    assert dummy_app.run_calls == [{"transport": "sse", "mount_path": "/api"}]
