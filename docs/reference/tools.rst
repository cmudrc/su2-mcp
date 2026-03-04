Tool Catalog
============

The current tool catalog is assembled by ``su2_mcp.fastmcp_server.build_server``.

Available tool groups
---------------------

- Session lifecycle: ``create_su2_session``, ``close_su2_session``,
  ``get_session_info``
- Config helpers: ``get_config_text``, ``parse_config``, ``update_config_entries``
- Mesh and setup: ``set_mesh``, ``generate_mesh_from_step``
- Solver execution: ``run_su2_solver``, ``generate_deformed_mesh``
- Results inspection: ``list_result_files``, ``get_result_file_base64``,
  ``read_history_csv``, ``sample_surface_solution``
- Availability and health: ``get_su2_status``, ``ping``

.. automodule:: su2_mcp.tools
   :members:
