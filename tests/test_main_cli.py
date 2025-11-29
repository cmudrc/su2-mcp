"""CLI and factory coverage for the MCP server entrypoint."""

from __future__ import annotations

from types import SimpleNamespace

from pytest import MonkeyPatch

from su2_mcp_server import __main__ as cli


class FakeServer:
    """Lightweight stand-in for FastMCP used in CLI tests."""

    def __init__(self) -> None:
        """Initialize default settings for test inspection."""
        self.settings = SimpleNamespace(
            host="127.0.0.1",
            port=8000,
            mount_path="/",
            sse_path="/sse",
            message_path="/messages/",
            streamable_http_path="/mcp",
        )
        self.run_calls: list[SimpleNamespace] = []

    def run(self, transport: str, mount_path: str | None = None) -> None:  # noqa: D401
        """Record the run parameters instead of launching servers."""
        self.run_calls.append(SimpleNamespace(transport=transport, mount_path=mount_path))


def test_apply_settings_configures_http_transport(monkeypatch: MonkeyPatch) -> None:
    """HTTP transport should map to streamable-http with the selected path."""
    fake_server = FakeServer()
    monkeypatch.setattr(cli, "build_server", lambda: fake_server)

    args = cli.parse_args(
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

    transport, mount_path, server = cli._apply_settings(args)

    assert transport == "streamable-http"
    assert mount_path is None
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 9001
    assert server.settings.streamable_http_path == "/custom"


def test_main_runs_with_sse_transport(monkeypatch: MonkeyPatch) -> None:
    """Main should run the server with the configured SSE mount path."""
    fake_server = FakeServer()
    monkeypatch.setattr(cli, "build_server", lambda: fake_server)

    cli.main(
        [
            "--transport",
            "sse",
            "--mount-path",
            "/api",
            "--sse-path",
            "/events",
        ]
    )

    assert fake_server.settings.mount_path == "/api"
    assert fake_server.settings.sse_path == "/events"
    assert len(fake_server.run_calls) == 1
    assert fake_server.run_calls[0].transport == "sse"
    assert fake_server.run_calls[0].mount_path == "/api"
