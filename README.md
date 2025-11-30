# SU2 MCP Server

A Modular Compute Protocol (MCP) server that exposes SU2 workflows (session setup, configuration, solver execution, and results inspection) via JSON-schema tools. Each SU2 session operates inside an isolated working directory containing configuration, mesh, and outputs.

## Features

- Session lifecycle management with per-session working directories.
- Configuration helpers for reading, parsing, and updating SU2 `.cfg` files.
- Mesh upload and automatic `MESH_FILENAME` synchronization.
- Safe solver execution wrappers with timeout and missing-binary handling.
- Utilities for inspecting output files, sampling surface data, and exporting results.
- Installation helper tools to verify SU2 availability.

## Development

### Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### Formatting, linting, and type checks

```bash
ruff check .
black .
mypy .
```

### Tests

```bash
pytest
```

### Running the server

The server is built with [`FastMCP`](https://github.com/modelcontextprotocol/python-sdk) to expose SU2 tooling with generated JSON Schema metadata. Install in editable mode to register the console script:

```bash
pip install -e .[dev]
```

#### StdIO (default)

Stream requests and responses over standard input/output with a single command:

```bash
su2-mcp-server --transport stdio
```

#### HTTP transports

Expose the MCP server over HTTP using either the standard HTTP transport (`--transport http`) or the Streamable HTTP variant (`--transport streamable-http`). Both respect host/port flags and path selection:

```bash
su2-mcp-server --transport http --host 0.0.0.0 --port 8002 --path /mcp
su2-mcp-server --transport streamable-http --host 0.0.0.0 --port 8002 --streamable-http-path /mcp
```

#### Server-Sent Events (SSE)

Expose the MCP server over HTTP with SSE. This starts a Starlette/uvicorn app on the configured host/port (defaults: `127.0.0.1:8000`) with the SSE stream mounted at `/sse`:

```bash
su2-mcp-server --transport sse --host 0.0.0.0 --port 8000 --mount-path / --sse-path /sse
```

Additional options let you control the Starlette mount path (`--mount-path`) and message transport path (`--message-path`). If you need to embed the server programmatically, call `su2_mcp_server.main.create_app` or `su2_mcp_server.fastmcp_server.build_server` and invoke `run` on the resulting `FastMCP` instance.

### Checking SU2 binaries

Use the `get_su2_status` MCP tool to report whether common SU2 binaries (e.g., `SU2_CFD`, `SU2_DEF`) are present on `PATH`.
You can call it directly in Python after installing the package:

```bash
python - <<'PY'
from su2_mcp_server.tools.su2_installation import get_su2_status

print(get_su2_status())
PY
```

To install SU2 alongside the MCP server, opt in to the extra dependency group when installing:

```bash
pip install su2-mcp-server[su2]
```
