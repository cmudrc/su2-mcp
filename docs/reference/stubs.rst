Deterministic CI Behavior
=========================

The package supports real SU2 solver calls, but default tests and examples do
not require SU2 binaries. They use deterministic filesystem-backed flows so CI
can validate payload contracts consistently.

Why this exists
---------------

- Local development stays lightweight.
- CI remains deterministic.
- Tool schemas and wiring can be validated without native solver dependencies.

What remains optional
---------------------

- ``run_su2_solver`` and ``generate_deformed_mesh`` will report structured
  missing-binary errors when solver executables are unavailable.
- ``generate_mesh_from_step`` requires the `gmsh` CLI.

.. automodule:: su2_mcp.su2_availability
   :members:
