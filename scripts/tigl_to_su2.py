#!/usr/bin/env python3
"""
End-to-end pipeline: TiGL (CPACS) → STL → Gmsh volume mesh → SU2

Usage:
    python tigl_to_su2.py <cpacs_file> [--output-dir <dir>]

This script:
1. Opens a CPACS model via the TiGL MCP server
2. Exports each component as STL
3. Merges STLs, checks/repairs watertightness
4. Creates a farfield box around the aircraft
5. Generates a volume mesh with Gmsh
6. Exports to SU2 format with FARFIELD + WALL markers
"""

import os
import sys
import json
import base64
import argparse
import tempfile
import struct
import numpy as np
import requests
import gmsh
from collections import defaultdict
from pathlib import Path

MCP_URL = "http://127.0.0.1:8000/mcp"


# ─────────────────────────────────────────────────────────────────────
# MCP client helpers
# ─────────────────────────────────────────────────────────────────────

class TiGLClient:
    def __init__(self, url=MCP_URL):
        self.url = url
        self.session_id = None
        self._mcp_sid = None
        self._msg_id = 0

    def connect(self):
        r = requests.get(
            self.url,
            headers={"Accept": "application/json, text/event-stream"},
            timeout=5,
        )
        self._mcp_sid = r.headers.get("mcp-session-id")
        if not self._mcp_sid:
            raise RuntimeError(f"No mcp-session-id header. Response: {r.text[:200]}")

        resp = self._post({
            "jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}, "logging": {}},
                "clientInfo": {"name": "pipeline", "version": "1.0"},
            },
        })
        print(f"  Connected to {resp['result']['serverInfo']['name']}")

    def open_cpacs(self, cpacs_path: str):
        xml = open(cpacs_path, "r", encoding="utf-8").read()
        resp = self._call("open_cpacs", {"source_type": "xml_string", "source": xml})
        self.session_id = self._extract(resp, "session_id")
        print(f"  Session: {self.session_id}")

    def list_components(self) -> list[dict]:
        resp = self._call("list_geometric_components", {"session_id": self.session_id})
        return self._extract(resp, "components")

    def export_stl(self, component_uid: str) -> bytes:
        resp = self._call("export_component_mesh", {
            "session_id": self.session_id,
            "component_uid": component_uid,
            "format": "stl",
        })
        b64 = self._extract(resp, "mesh_base64")
        return base64.b64decode(b64)

    def export_fused_step(self) -> bytes:
        resp = self._call("export_configuration_cad", {
            "session_id": self.session_id,
            "format": "step",
        })
        b64 = self._extract(resp, "cad_base64")
        source = self._extract(resp, "source")
        print(f"  STEP source: {source}")
        return base64.b64decode(b64)

    def _next_id(self):
        self._msg_id += 1
        return self._msg_id

    def _call(self, tool: str, args: dict) -> dict:
        return self._post({
            "jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        })

    def _post(self, payload: dict) -> dict:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "mcp-session-id": self._mcp_sid,
        }
        r = requests.post(self.url, headers=headers, data=json.dumps(payload), timeout=120)
        lines = [ln for ln in r.text.splitlines() if ln.startswith("data: ")]
        if not lines:
            raise RuntimeError(f"No SSE data lines. Response: {r.text[:500]}")
        resp = json.loads(lines[-1][6:])
        if resp.get("result", {}).get("isError"):
            raise RuntimeError(f"MCP error: {json.dumps(resp, indent=2)}")
        return resp

    def _extract(self, resp: dict, key: str):
        res = resp.get("result", {})
        sc = res.get("structuredContent") or {}
        if key in sc:
            return sc[key]
        for item in res.get("content", []):
            if item.get("type") == "text":
                data = json.loads(item["text"])
                if key in data:
                    return data[key]
        raise KeyError(f"Key '{key}' not found in response")


# ─────────────────────────────────────────────────────────────────────
# STL helpers
# ─────────────────────────────────────────────────────────────────────

def read_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Parse STL (auto-detect ASCII/binary) → (vertices Nx3x3, normals Nx3)."""
    text = data[:80].decode("ascii", errors="ignore")
    if text.strip().startswith("solid") and b"facet" in data[:1000]:
        return _read_ascii_stl(data)
    return _read_binary_stl(data)


def _read_binary_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    n_tris = struct.unpack("<I", data[80:84])[0]
    tris = np.zeros((n_tris, 3, 3), dtype=np.float64)
    normals = np.zeros((n_tris, 3), dtype=np.float64)
    offset = 84
    for i in range(n_tris):
        rec = struct.unpack("<12fH", data[offset:offset+50])
        normals[i] = rec[0:3]
        tris[i, 0] = rec[3:6]
        tris[i, 1] = rec[6:9]
        tris[i, 2] = rec[9:12]
        offset += 50
    return tris, normals


def _read_ascii_stl(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    text = data.decode("ascii", errors="ignore")
    tris_list = []
    normals_list = []
    current_normal = [0.0, 0.0, 0.0]
    verts = []
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == "facet" and parts[1] == "normal":
            current_normal = [float(parts[2]), float(parts[3]), float(parts[4])]
            verts = []
        elif parts[0] == "vertex":
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif parts[0] == "endfacet":
            if len(verts) == 3:
                tris_list.append(verts)
                normals_list.append(current_normal)
    return np.array(tris_list), np.array(normals_list)


def merge_stls(stl_list: list[bytes]) -> tuple[np.ndarray, np.ndarray]:
    all_tris = []
    all_normals = []
    for data in stl_list:
        tris, normals = read_stl(data)
        all_tris.append(tris)
        all_normals.append(normals)
    return np.concatenate(all_tris), np.concatenate(all_normals)


def write_binary_stl(path: str, tris: np.ndarray, normals: np.ndarray):
    n = len(tris)
    with open(path, "wb") as f:
        f.write(b"\x00" * 80)
        f.write(struct.pack("<I", n))
        for i in range(n):
            f.write(struct.pack("<3f", *normals[i]))
            for j in range(3):
                f.write(struct.pack("<3f", *tris[i, j]))
            f.write(struct.pack("<H", 0))


def check_watertight(tris: np.ndarray) -> tuple[bool, int]:
    """Check if a triangle mesh is watertight (every edge shared by exactly 2 tris)."""
    # Weld vertices by rounding to a tolerance
    tol = 1e-6
    flat = tris.reshape(-1, 3)
    rounded = np.round(flat / tol) * tol
    _, inverse = np.unique(rounded, axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)

    edge_count = defaultdict(int)
    for f in faces:
        for e in [(min(f[0], f[1]), max(f[0], f[1])),
                  (min(f[1], f[2]), max(f[1], f[2])),
                  (min(f[0], f[2]), max(f[0], f[2]))]:
            edge_count[e] += 1

    open_edges = sum(1 for c in edge_count.values() if c == 1)
    nm_edges = sum(1 for c in edge_count.values() if c > 2)
    return open_edges == 0 and nm_edges == 0, open_edges


# ─────────────────────────────────────────────────────────────────────
# Gmsh meshing
# ─────────────────────────────────────────────────────────────────────

def boolean_union_stls(stl_data_list: list[tuple[str, bytes]], output_path: str) -> bool:
    """Boolean-union all component STLs into a single watertight mesh using manifold3d."""
    import trimesh

    meshes = []
    for uid, data in stl_data_list:
        tris, normals = read_stl(data)
        verts = tris.reshape(-1, 3)
        faces = np.arange(len(verts)).reshape(-1, 3)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        print(f"    {uid}: {mesh.vertices.shape[0]} vertices, {mesh.faces.shape[0]} faces, "
              f"watertight={mesh.is_watertight}")

        if not mesh.is_watertight:
            # pymeshfix can close small holes on individual components
            try:
                import pymeshfix
                tin = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
                tin.repair(joincomp=True, remove_smallest_components=False)
                mesh = trimesh.Trimesh(vertices=tin.points, faces=tin.faces, process=True)
                print(f"    {uid} repaired: {mesh.vertices.shape[0]} verts, "
                      f"watertight={mesh.is_watertight}")
            except Exception as e:
                print(f"    {uid} repair failed: {e}")

        meshes.append(mesh)

    # Compute boolean union
    print("  Computing boolean union (manifold3d)...")
    result = meshes[0]
    for i, m in enumerate(meshes[1:], 1):
        try:
            result = result.union(m)
            print(f"    After union with {stl_data_list[i][0]}: "
                  f"{result.vertices.shape[0]} verts, {result.faces.shape[0]} faces, "
                  f"watertight={result.is_watertight}")
        except Exception as e:
            print(f"    Union with {stl_data_list[i][0]} failed: {e}")
            print(f"    Falling back to simple concatenation")
            result = trimesh.util.concatenate([result, m])

    # Repair the unioned mesh to fix self-intersecting triangles
    import pymeshfix
    print("  Repairing self-intersections with pymeshfix...")
    tin = pymeshfix.MeshFix(result.vertices, result.faces)
    print(f"    Before: {tin.points.shape[0]} verts, {tin.faces.shape[0]} faces")
    tin.repair(joincomp=False, remove_smallest_components=False)
    result = trimesh.Trimesh(vertices=tin.points, faces=tin.faces, process=True)
    print(f"    After: {result.vertices.shape[0]} verts, {result.faces.shape[0]} faces, "
          f"watertight={result.is_watertight}")

    result.export(output_path)
    print(f"  Wrote {output_path}: {result.vertices.shape[0]} verts, "
          f"{result.faces.shape[0]} faces, watertight={result.is_watertight}")
    return result.is_watertight


def create_volume_mesh_from_step(step_path: str, su2_path: str, farfield_factor: float = 10.0):
    """Import fused STEP (closed solid), create farfield, BooleanFragments, mesh, export SU2."""
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)

    print(f"  Importing {step_path}...")
    gmsh.model.occ.importShapes(step_path)
    gmsh.model.occ.synchronize()

    volumes = gmsh.model.getEntities(3)
    surfaces = gmsh.model.getEntities(2)
    print(f"  Imported: {len(volumes)} volumes, {len(surfaces)} surfaces")

    # Get bounding box
    xmin_a = ymin_a = zmin_a = float("inf")
    xmax_a = ymax_a = zmax_a = float("-inf")
    for dim, tag in gmsh.model.getEntities():
        if dim >= 1:
            bb = gmsh.model.getBoundingBox(dim, tag)
            xmin_a = min(xmin_a, bb[0]); ymin_a = min(ymin_a, bb[1]); zmin_a = min(zmin_a, bb[2])
            xmax_a = max(xmax_a, bb[3]); ymax_a = max(ymax_a, bb[4]); zmax_a = max(zmax_a, bb[5])

    cx = (xmin_a + xmax_a) / 2
    cy = (ymin_a + ymax_a) / 2
    cz = (zmin_a + zmax_a) / 2
    span = max(xmax_a - xmin_a, ymax_a - ymin_a, zmax_a - zmin_a)
    ff_half = span * farfield_factor / 2

    print(f"  Aircraft bbox: [{xmin_a:.2f}, {ymin_a:.2f}, {zmin_a:.2f}] "
          f"to [{xmax_a:.2f}, {ymax_a:.2f}, {zmax_a:.2f}]")
    print(f"  Span: {span:.2f}, Farfield: {ff_half*2:.1f}")

    # Create farfield box
    box = gmsh.model.occ.addBox(
        cx - ff_half, cy - ff_half, cz - ff_half,
        2 * ff_half, 2 * ff_half, 2 * ff_half,
    )
    gmsh.model.occ.synchronize()

    # BooleanFragments: produces conforming volumes sharing the aircraft boundary
    aircraft_dim_tags = volumes if volumes else [(2, t) for _, t in surfaces]
    print(f"  BooleanFragments: box + {len(aircraft_dim_tags)} aircraft entities...")

    result, result_map = gmsh.model.occ.fragment(
        [(3, box)], aircraft_dim_tags
    )
    gmsh.model.occ.synchronize()

    frag_vols = gmsh.model.getEntities(3)
    frag_surfs = gmsh.model.getEntities(2)
    print(f"  After fragment: {len(frag_vols)} volumes, {len(frag_surfs)} surfaces")

    # Identify fluid vs solid volumes via result_map
    aircraft_vol_tags = set()
    for i in range(1, len(result_map)):
        for dim, tag in result_map[i]:
            if dim == 3:
                aircraft_vol_tags.add(tag)

    fluid_vol_tags = [t for _, t in frag_vols if t not in aircraft_vol_tags]
    print(f"  Fluid volumes: {len(fluid_vol_tags)}, Aircraft volumes: {len(aircraft_vol_tags)}")

    if not fluid_vol_tags:
        fluid_vol_tags = [t for _, t in frag_vols]

    # Classify boundary surfaces
    ff_bounds = [cx - ff_half, cx + ff_half, cy - ff_half, cy + ff_half, cz - ff_half, cz + ff_half]
    eps = span * 0.001

    farfield_surf_tags = set()
    for dim, tag in frag_surfs:
        bb = gmsh.model.getBoundingBox(dim, tag)
        for ci, vals in [(0, [ff_bounds[0], ff_bounds[1]]),
                         (1, [ff_bounds[2], ff_bounds[3]]),
                         (2, [ff_bounds[4], ff_bounds[5]])]:
            lo, hi = bb[ci], bb[ci + 3]
            for val in vals:
                if abs(lo - val) < eps and abs(hi - val) < eps:
                    farfield_surf_tags.add(tag)

    fluid_boundary_surfs = set()
    for vtag in fluid_vol_tags:
        boundary = gmsh.model.getBoundary([(3, vtag)], oriented=False)
        for dim, stag in boundary:
            if dim == 2:
                fluid_boundary_surfs.add(stag)

    wall_surf_tags = fluid_boundary_surfs - farfield_surf_tags

    print(f"  FARFIELD: {len(farfield_surf_tags)} surfaces")
    print(f"  WALL: {len(wall_surf_tags)} surfaces")

    # Physical groups
    gmsh.model.addPhysicalGroup(3, fluid_vol_tags, name="FLUID")
    if farfield_surf_tags:
        gmsh.model.addPhysicalGroup(2, sorted(farfield_surf_tags), name="FARFIELD")
    if wall_surf_tags:
        gmsh.model.addPhysicalGroup(2, sorted(wall_surf_tags), name="WALL")

    # Mesh sizing
    char_near = span / 50
    char_far = span
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", char_near / 5)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", char_far)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Algorithm3D", 4)  # Netgen
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)

    for stag in wall_surf_tags:
        pts = gmsh.model.getBoundary([(2, stag)], recursive=True)
        for dim, ptag in pts:
            if dim == 0:
                try:
                    gmsh.model.mesh.setSize([(0, ptag)], char_near)
                except Exception:
                    pass

    print("  Meshing (this may take a minute)...")
    gmsh.model.mesh.generate(3)

    # Stats
    node_tags, _, _ = gmsh.model.mesh.getNodes()
    total_3d = 0
    for dim, tag in gmsh.model.getEntities(3):
        etypes, etags, _ = gmsh.model.mesh.getElements(dim, tag)
        total_3d += sum(len(et) for et in etags)

    print(f"  Mesh: {len(node_tags)} nodes, {total_3d} 3D elements")

    for name, tags in [("FARFIELD", farfield_surf_tags), ("WALL", wall_surf_tags)]:
        count = 0
        for stag in tags:
            etypes, etags, _ = gmsh.model.mesh.getElements(2, stag)
            count += sum(len(et) for et in etags)
        print(f"  {name}: {count} boundary elements")

    gmsh.write(su2_path)
    print(f"  Wrote {su2_path}")

    msh_path = su2_path.replace(".su2", ".msh")
    gmsh.write(msh_path)
    print(f"  Wrote {msh_path}")

    gmsh.finalize()
    return total_3d > 0


def create_volume_mesh(stl_path: str, su2_path: str, farfield_factor: float = 10.0):
    """Import repaired STL, create farfield box (GEO), define volume with hole, mesh, export SU2."""
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)

    # ── Import repaired STL ──
    print(f"  Importing {stl_path}...")
    gmsh.merge(stl_path)

    print("  Classifying surfaces...")
    gmsh.model.mesh.classifySurfaces(
        angle=40 * 3.14159 / 180,
        boundary=True,
        forReparametrization=True,
        curveAngle=180 * 3.14159 / 180,
    )
    gmsh.model.mesh.createGeometry()

    # Clean up duplicate nodes/elements from the classified mesh
    gmsh.model.mesh.removeDuplicateNodes()
    gmsh.model.mesh.removeDuplicateElements()

    aircraft_surfs = gmsh.model.getEntities(2)
    aircraft_surf_tags = [t for _, t in aircraft_surfs]
    print(f"  Classified into {len(aircraft_surfs)} surfaces")

    # ── Bounding box ──
    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    coords = node_coords.reshape(-1, 3)
    bb_min = coords.min(axis=0)
    bb_max = coords.max(axis=0)
    cx, cy, cz = (bb_min + bb_max) / 2
    span = (bb_max - bb_min).max()
    ff_half = span * farfield_factor / 2

    print(f"  Aircraft bbox: [{bb_min[0]:.2f}, {bb_min[1]:.2f}, {bb_min[2]:.2f}] "
          f"to [{bb_max[0]:.2f}, {bb_max[1]:.2f}, {bb_max[2]:.2f}]")
    print(f"  Span: {span:.2f}, Farfield half-size: {ff_half:.1f}")

    # ── Create farfield box (GEO kernel) ──
    xm, xp = cx - ff_half, cx + ff_half
    ym, yp = cy - ff_half, cy + ff_half
    zm, zp = cz - ff_half, cz + ff_half

    p = [
        gmsh.model.geo.addPoint(xm, ym, zm),
        gmsh.model.geo.addPoint(xp, ym, zm),
        gmsh.model.geo.addPoint(xp, yp, zm),
        gmsh.model.geo.addPoint(xm, yp, zm),
        gmsh.model.geo.addPoint(xm, ym, zp),
        gmsh.model.geo.addPoint(xp, ym, zp),
        gmsh.model.geo.addPoint(xp, yp, zp),
        gmsh.model.geo.addPoint(xm, yp, zp),
    ]

    l = [
        gmsh.model.geo.addLine(p[0], p[1]),
        gmsh.model.geo.addLine(p[1], p[2]),
        gmsh.model.geo.addLine(p[2], p[3]),
        gmsh.model.geo.addLine(p[3], p[0]),
        gmsh.model.geo.addLine(p[4], p[5]),
        gmsh.model.geo.addLine(p[5], p[6]),
        gmsh.model.geo.addLine(p[6], p[7]),
        gmsh.model.geo.addLine(p[7], p[4]),
        gmsh.model.geo.addLine(p[0], p[4]),
        gmsh.model.geo.addLine(p[1], p[5]),
        gmsh.model.geo.addLine(p[2], p[6]),
        gmsh.model.geo.addLine(p[3], p[7]),
    ]

    cl_bottom = gmsh.model.geo.addCurveLoop([l[0], l[1], l[2], l[3]])
    cl_top = gmsh.model.geo.addCurveLoop([l[4], l[5], l[6], l[7]])
    cl_front = gmsh.model.geo.addCurveLoop([l[0], l[9], -l[4], -l[8]])
    cl_right = gmsh.model.geo.addCurveLoop([l[1], l[10], -l[5], -l[9]])
    cl_back = gmsh.model.geo.addCurveLoop([l[2], l[11], -l[6], -l[10]])
    cl_left = gmsh.model.geo.addCurveLoop([l[3], l[8], -l[7], -l[11]])

    s_bottom = gmsh.model.geo.addPlaneSurface([cl_bottom])
    s_top = gmsh.model.geo.addPlaneSurface([cl_top])
    s_front = gmsh.model.geo.addPlaneSurface([cl_front])
    s_right = gmsh.model.geo.addPlaneSurface([cl_right])
    s_back = gmsh.model.geo.addPlaneSurface([cl_back])
    s_left = gmsh.model.geo.addPlaneSurface([cl_left])
    box_surf_tags = [s_bottom, s_top, s_front, s_right, s_back, s_left]

    # ── Fluid volume: box with aircraft hole ──
    sl_box = gmsh.model.geo.addSurfaceLoop(box_surf_tags)
    sl_aircraft = gmsh.model.geo.addSurfaceLoop(aircraft_surf_tags)
    fluid_vol = gmsh.model.geo.addVolume([sl_box, sl_aircraft])

    gmsh.model.geo.synchronize()
    print(f"  Created fluid volume {fluid_vol} (box with aircraft hole)")

    # ── Physical groups ──
    gmsh.model.addPhysicalGroup(3, [fluid_vol], name="FLUID")
    gmsh.model.addPhysicalGroup(2, box_surf_tags, name="FARFIELD")
    gmsh.model.addPhysicalGroup(2, aircraft_surf_tags, name="WALL")

    # ── Mesh sizing ──
    char_near = span / 50
    char_far = span
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", char_near / 5)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", char_far)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Algorithm3D", 4)  # Netgen
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)

    # ── Mesh ──
    print("  Meshing (this may take a minute)...")
    gmsh.model.mesh.generate(3)

    # ── Stats ──
    node_tags, _, _ = gmsh.model.mesh.getNodes()
    total_3d = 0
    for dim, tag in gmsh.model.getEntities(3):
        etypes, etags, _ = gmsh.model.mesh.getElements(dim, tag)
        total_3d += sum(len(et) for et in etags)

    print(f"  Mesh: {len(node_tags)} nodes, {total_3d} 3D elements")

    for label, tags in [("FARFIELD", box_surf_tags), ("WALL", aircraft_surf_tags)]:
        count = 0
        for stag in tags:
            etypes, etags, _ = gmsh.model.mesh.getElements(2, stag)
            count += sum(len(et) for et in etags)
        print(f"  {label}: {count} boundary elements")

    # ── Export ──
    gmsh.write(su2_path)
    print(f"  Wrote {su2_path}")

    msh_path = su2_path.replace(".su2", ".msh")
    gmsh.write(msh_path)
    print(f"  Wrote {msh_path}")

    gmsh.finalize()
    return total_3d > 0


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TiGL CPACS → SU2 pipeline")
    parser.add_argument("cpacs", help="Path to CPACS XML file")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory")
    parser.add_argument("--farfield", "-f", type=float, default=10.0,
                        help="Farfield size as multiple of aircraft span")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: TiGL MCP — connect and open CPACS ──
    print("\n[1/4] Connecting to TiGL MCP server...")
    client = TiGLClient()
    client.connect()
    client.open_cpacs(args.cpacs)

    components = client.list_components()
    print(f"  Components: {[c['uid'] for c in components]}")

    # ── Step 2: Export fused STEP (closed solid) ──
    print("\n[2/4] Exporting fused STEP from TiGL...")
    step_data = client.export_fused_step()
    step_path = str(out_dir / "aircraft_fused.step")
    with open(step_path, "wb") as f:
        f.write(step_data)
    print(f"  Wrote {step_path} ({len(step_data)} bytes)")

    # ── Step 3: Volume mesh ──
    print("\n[3/4] Creating volume mesh...")
    su2_path = str(out_dir / "aircraft_volume.su2")
    success = create_volume_mesh_from_step(step_path, su2_path, farfield_factor=args.farfield)

    if success:
        print(f"\n[4/4] Mesh ready: {su2_path}")
        print("  Run SU2 with:")
        print(f"    SU2_CFD euler.cfg")
    else:
        print("\nERROR: Mesh generation failed")
        return

    # ── Write a default SU2 config ──
    cfg_path = str(out_dir / "euler.cfg")
    with open(cfg_path, "w") as f:
        f.write("""\
% ----------- SOLVER -----------%
SOLVER= EULER
MATH_PROBLEM= DIRECT

% ----------- FREESTREAM -----------%
MACH_NUMBER= 0.78
AOA= 2.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= 101325.0
FREESTREAM_TEMPERATURE= 288.15
REF_DIMENSIONALIZATION= DIMENSIONAL

% ----------- MESH -----------%
MESH_FILENAME= aircraft_volume.su2
MESH_FORMAT= SU2

% ----------- BOUNDARY CONDITIONS -----------%
MARKER_FAR= ( FARFIELD )
MARKER_EULER= ( WALL )
MARKER_PLOTTING= ( WALL )
MARKER_MONITORING= ( WALL )

% ----------- REFERENCE -----------%
REF_ORIGIN_MOMENT_X= 15.0
REF_ORIGIN_MOMENT_Y= 0.0
REF_ORIGIN_MOMENT_Z= 0.0
REF_LENGTH= 4.2
REF_AREA= 122.4

% ----------- NUMERICS -----------%
NUM_METHOD_GRAD= GREEN_GAUSS
CFL_NUMBER= 1.0
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.1, 2.0, 1.0, 1e10 )
CONV_NUM_METHOD_FLOW= ROE
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.1
TIME_DISCRE_FLOW= EULER_IMPLICIT
LINEAR_SOLVER= FGMRES
LINEAR_SOLVER_PREC= ILU
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 10

% ----------- CONVERGENCE -----------%
ITER= 250
CONV_RESIDUAL_MINVAL= -10

% ----------- OUTPUT -----------%
OUTPUT_FILES= ( RESTART, PARAVIEW )
OUTPUT_WRT_FREQ= 50
CONV_FILENAME= history
HISTORY_OUTPUT= ( ITER, RMS_RES, LIFT, DRAG, AERO_COEFF )
SCREEN_OUTPUT= INNER_ITER, RMS_DENSITY, RMS_MOMENTUM-X, RMS_ENERGY, LIFT, DRAG
""")
    print(f"  Wrote default config: {cfg_path}")


if __name__ == "__main__":
    main()
