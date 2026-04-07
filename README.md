# su2-mcp

`su2-mcp` exposes SU2 session lifecycle, config editing, solver execution, and
results inspection through an MCP server.

## Features

- Session lifecycle management with per-session working directories.
- Config helpers for reading, parsing, and updating SU2 `.cfg` files.
- Mesh upload and automatic `MESH_FILENAME` synchronization.
- Optional STEP -> SU2 mesh conversion via `gmsh` (`generate_mesh_from_step`).
- Solver wrappers for `SU2_CFD` and `SU2_DEF` with timeout/missing-binary
  handling.
- Result-file listing, base64 download, history CSV parsing, and surface sampling.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Run the Server

### StdIO (default)

```bash
su2-mcp --transport stdio
```

### HTTP transports

```bash
su2-mcp --transport http --host 0.0.0.0 --port 8002 --path /mcp
su2-mcp --transport streamable-http --host 0.0.0.0 --port 8002 --streamable-http-path /mcp
```

### Server-Sent Events (SSE)

```bash
su2-mcp --transport sse --host 0.0.0.0 --port 8000 --mount-path / --sse-path /sse
```

Programmatic entrypoints are available from `su2_mcp.main`.

## Development

```bash
make dev
make lint
make type
make test
make docs
```

Full local CI-style gate:

```bash
make ci
```

## Checking SU2 binaries

The MCP tool `get_su2_status` reports availability of common SU2 binaries
(`SU2_CFD`, `SU2_CFD_MPI`, `SU2_DEF`).

## Optional SU2 dependency extra

```bash
pip install .[su2]
```

## System dependencies

The Python package is pure Python, but some tools rely on external executables:

- `run_su2_solver` / `generate_deformed_mesh`: requires SU2 binaries on `PATH`
- `generate_mesh_from_step`: requires `gmsh` on `PATH`

## Shared-CPACS Integration

This MCP includes a **CPACS adapter** (`src/su2_mcp/cpacs_adapter.py`) that
bridges SU2 to the shared-CPACS aircraft analysis pipeline.

### What it does

The adapter reads reference geometry and flight conditions from CPACS, meshes
STEP files via Gmsh, runs real `SU2_CFD` Euler simulations, parses CL/CD from
`history.csv`, and writes aerodynamic results into `//analysisResults/aero`.

| Direction | XPath |
|-----------|-------|
| **Reads** | `.//vehicles/aircraft/model/reference`, `.//analysisResults/tigl` |
| **Writes** | `.//vehicles/aircraft/model/analysisResults/aero` (CL, CD, L/D, solver info) |

### Running as part of the pipeline

```bash
python pipeline/shared_cpacs_orchestrator.py D150_v30.xml --mcps tigl su2 pycycle mission
```

See [cmudrc/aircraft-analysis](https://github.com/cmudrc/aircraft-analysis) for
full pipeline documentation, versioning details, and installation instructions.

### Related MCP servers

| MCP | Repository |
|-----|-----------|
| TiGL (geometry) | [cmudrc/tigl-mcp](https://github.com/cmudrc/tigl-mcp) |
| pyCycle (engine cycle) | [cmudrc/pycycle-mcp](https://github.com/cmudrc/pycycle-mcp) |
| Mission (trajectory/fuel) | [cmudrc/mission-mcp](https://github.com/cmudrc/mission-mcp) |
