"""CLI and factory coverage for the MCP server entrypoint."""

from __future__ import annotations

from types import SimpleNamespace

from pytest import MonkeyPatch

from su2_mcp_server import main


def test_create_app_applies_server_settings() -> None:
    """create_app should forward configuration values to FastMCP settings."""
    app = main.create_app(
        host="0.0.0.0",
        port=9001,
        mount_path="/api",
        sse_path="/events",
        message_path="/msg/",
        streamable_http_path="/mcp-http",
        json_response=True,
        stateless_http=True,
    )

    assert app.settings.host == "0.0.0.0"
    assert app.settings.port == 9001
    assert app.settings.mount_path == "/api"
    assert app.settings.sse_path == "/events"
    assert app.settings.message_path == "/msg/"
    assert app.settings.streamable_http_path == "/mcp-http"
    assert app.settings.json_response is True
    assert app.settings.stateless_http is True


def test_main_uses_cli_arguments(monkeypatch: MonkeyPatch) -> None:
    """Main should construct the app with CLI args and invoke run with transport."""
    recorded_kwargs: dict[str, object] = {}
    run_calls: list[SimpleNamespace] = []

    class FakeApp:
        def run(self, transport: str, mount_path: str | None = None) -> None:  # noqa: D401
            """Record the run parameters instead of launching servers."""
            run_calls.append(SimpleNamespace(transport=transport, mount_path=mount_path))

    def fake_create_app(**kwargs: object) -> FakeApp:
        recorded_kwargs.update(kwargs)
        return FakeApp()

    monkeypatch.setattr(main, "create_app", fake_create_app)

    main.main(
        [
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
            "--mount-path",
            "/api",
            "--sse-path",
            "/events",
            "--message-path",
            "/msg/",
            "--streamable-http-path",
            "/mcp-http",
            "--json-response",
            "--stateless-http",
        ]
    )

    assert recorded_kwargs == {
        "host": "0.0.0.0",
        "port": 9001,
        "mount_path": "/api",
        "sse_path": "/events",
        "message_path": "/msg/",
        "streamable_http_path": "/mcp-http",
        "json_response": True,
        "stateless_http": True,
    }
    assert len(run_calls) == 1
    assert run_calls[0].transport == "streamable-http"
    assert run_calls[0].mount_path is None
