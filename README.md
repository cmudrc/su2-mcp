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

### TiGL → SU2 → pyCycle pipeline

An orchestration script (`pipeline/tigl_to_su2.py`) chains all three MCP servers into a single automated run:

```
CPACS XML → [TiGL MCP] → STEP → [Gmsh] → SU2 mesh → [SU2] → CL/CD → [pyCycle MCP] → TSFC, fuel flow
```

1. **TiGL MCP** (port 8000): Open CPACS, export configuration as watertight STEP.
2. **SU2 MCP / Gmsh**: Volume mesh from STEP (BooleanFragments, FARFIELD/WALL markers), then Euler CFD to get CL/CD.
3. **pyCycle MCP** (port 8001): Flight conditions + drag → engine sizing (thrust, TSFC, fuel flow).

#### Config-driven runs

The pipeline uses a YAML config file (`pipeline_config.yaml`) that controls all ~15 user-relevant parameters. CLI arguments override config values.

```bash
# Run with config file
python pipeline/tigl_to_su2.py D150.xml --config pipeline/pipeline_config.yaml -o output/

# Override specific values via CLI
python pipeline/tigl_to_su2.py D150.xml -c pipeline/pipeline_config.yaml --mach 0.85 --density 80

# Defaults only (no config file needed)
python pipeline/tigl_to_su2.py D150.xml -o output/
```

Config file sections: `flight` (mach, aoa, altitude), `aircraft` (ref_area, ref_length), `meshing` (surface_density, farfield_factor, algorithm), `cfd` (iterations, CFL, limiter), `engine` (type, default thrust). A `resolved_config.yaml` is saved alongside outputs for reproducibility.

#### Customisable parameters

| Category | Key parameters | Default |
|----------|---------------|---------|
| Flight | mach, aoa, altitude | 0.78, 2°, 35,000 ft |
| Mesh quality | `surface_density` (span/N) | 30 (coarse) — set 80-150 for smooth |
| CFD | iterations, CFL, limiter_coeff | 250, 1.0, 0.1 |
| Engine | type, default_thrust_lbf | turbofan, 5900 |

#### Hardcoded (not exposed via config)

- Solver: Euler (inviscid) — RANS support is a future milestone
- Flux scheme: ROE with Venkatakrishnan limiter
- pyCycle engine cycle internals (duct losses, bleed fractions, nozzle Cv)
- TiGL STEP deflection tolerance (0.001)

### Running SU2 when not installed locally

SU2 is available inside the [tigl-mcp](https://github.com/cmudrc/tigl-mcp) Docker image. Copy your mesh and config into the running container:

```bash
docker cp output/aircraft_volume.su2 <container>:/tmp/aircraft_volume.su2
docker cp output/euler.cfg <container>:/tmp/euler.cfg
docker exec <container> bash -c "cd /tmp && conda run -n tigl SU2_CFD euler.cfg"
docker cp <container>:/tmp/history.csv output/
docker cp <container>:/tmp/vol_solution.vtu output/
```

### System-level dependencies

These cannot be pip-installed and require conda or system packages:

- **SU2** (`SU2_CFD`): `conda install -c conda-forge su2` or use the Docker image
- **Gmsh** (Python API): `pip install gmsh` (or `conda install -c conda-forge gmsh`)

The MCP server itself (`pip install .`) is pure Python and installs cleanly.
