# SU2 MCP Server

A Modular Compute Protocol (MCP) server that exposes SU2 workflows (session setup, configuration, solver execution, and results inspection) via JSON-schema tools. Each SU2 session operates inside an isolated working directory containing configuration, mesh, and outputs.

## Features

- Session lifecycle management with per-session working directories.
- Configuration helpers for reading, parsing, and updating SU2 `.cfg` files.
- Mesh upload and automatic `MESH_FILENAME` synchronization.
- **STEP → SU2 mesh**: `generate_mesh_from_step` builds a 3D fluid mesh from a STEP file (e.g. from TiGL) using a bundled Gmsh .geo template (aircraft volume + farfield box, FARFIELD/WALL markers). Requires the `gmsh` CLI on PATH.
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

### TiGL → SU2 pipeline (external agent)

An external agent can chain TiGL MCP, SU2 MCP, and (optionally) Pycycle MCP to design and analyze an aircraft:

1. **TiGL MCP**: Open CPACS, export configuration as STEP (base64).
2. **SU2 MCP**: `create_su2_session` → `generate_mesh_from_step(session_id, step_base64)` (requires `gmsh` on PATH) → `update_config_entries` to set Euler/freestream and `MARKER_FAR`/`MARKER_EULER` to match the mesh markers (FARFIELD, WALL) → `run_su2_solver` → `list_result_files` / `read_history_csv` / `get_result_file_base64` for results.
3. **Pycycle MCP**: Use for propulsion/cycle analysis as needed.

For a single Docker environment that has TiGL, Gmsh, and SU2, use the `tigl-mcp` image (which includes SU2 and Gmsh) and run the SU2 MCP server in that same environment so `generate_mesh_from_step` can call `gmsh`.

### Running the server when SU2 is not installed locally

The server runs `SU2_CFD` when you call `run_su2_solver`. If SU2 is not on your machine, run the SU2 MCP server inside a container that has SU2 (e.g. the [tigl-mcp](https://github.com/cmudrc/tigl-mcp) Docker image). From the host, mount this repo and start the server:

```bash
docker run --rm -p 8002:8002 -v /path/to/su2-mcp:/app/su2-mcp tigl-mcp:dev \
  bash -lc "pip install -e /app/su2-mcp && su2-mcp-server --transport http --host 0.0.0.0 --port 8002 --path /mcp"
```

Then clients can connect to `http://localhost:8002/mcp`. For a pre-built script that does this, see the parent repo that contains both tigl-mcp and su2-mcp.
