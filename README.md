# SU2 MCP Server

A Modular Compute Protocol (MCP) server that exposes SU2 workflows (session setup, configuration, solver execution, and results inspection) via JSON-schema tools. Each SU2 session operates inside an isolated working directory containing configuration, mesh, and outputs.

## Features

- Session lifecycle management with per-session working directories.
- Configuration helpers for reading, parsing, and updating SU2 `.cfg` files.
- Mesh upload and automatic `MESH_FILENAME` synchronization.
- Safe solver execution wrappers with timeout and missing-binary handling.
- Utilities for inspecting output files, sampling surface data, and exporting results.

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

The server is built with [`FastMCP`](https://github.com/modelcontextprotocol/python-sdk) to expose SU2 tooling with generated JSON Schema metadata. Use the module entry point for a familiar MCP CLI experience and select the transport you need with flags.

#### StdIO (default)

Stream requests and responses over standard input/output with a single command:

```bash
python -m su2_mcp_server --transport stdio
```

#### Server-Sent Events (SSE)

Expose the MCP server over HTTP with SSE. This starts a Starlette/uvicorn app on the configured host/port (defaults: `127.0.0.1:8000`) with the SSE stream mounted at `/sse`:

```bash
python -m su2_mcp_server --transport sse --host 0.0.0.0 --port 8000 --sse-path /sse
```

#### Streamable HTTP

Serve the MCP API over the Streamable HTTP transport when clients prefer plain JSON requests. The default endpoint mounts at `/mcp` on the configured host/port:

```bash
python -m su2_mcp_server --transport streamable-http --host 0.0.0.0 --port 8000 --streamable-http-path /mcp
```

Additional options let you control the Starlette mount path (`--mount-path`), message transport path (`--message-path`), JSON response mode (`--json-response`), and stateless HTTP behavior (`--stateless-http`). If you need to embed the server programmatically, call `su2_mcp_server.main.create_app` with the same arguments and invoke `run` on the resulting `FastMCP` instance.
