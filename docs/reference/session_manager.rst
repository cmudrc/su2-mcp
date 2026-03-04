Session Management
==================

``SessionManager`` stores per-session working directories, config paths, mesh
paths, and last-run metadata.

Current guarantees
------------------

- Session creation returns an opaque UUID string.
- Missing sessions raise ``KeyError`` with stable error text.
- Closing a session can optionally remove the working directory.

.. automodule:: su2_mcp.session_manager
   :members:
