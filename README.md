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

The server is built with [`FastMCP`](https://github.com/modelcontextprotocol/python-sdk) to expose SU2 tooling with generated JSON Schema metadata. The `create_app` factory in `su2_mcp_server/main.py` wires every tool into a `FastMCP` instance that can run over stdio or other transports supported by the MCP SDK.

```bash
python -m su2_mcp_server.main
```

`python -m su2_mcp_server.main` bootstraps the FastMCP app and serves it over stdio; callers can also import `su2_mcp_server.main.APP` or invoke `create_app()` to embed the server.
