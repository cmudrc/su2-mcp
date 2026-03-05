CLI and Transports
==================

The ``su2-mcp`` command and ``python -m su2_mcp`` entrypoint both use
``su2_mcp.main``.

Supported transports
--------------------

- ``stdio`` for editor and local MCP integrations
- ``http`` as an alias that maps to streamable HTTP using ``--path``
- ``sse`` for server-sent events
- ``streamable-http`` for FastMCP streamable HTTP mode

The parser defaults to ``stdio``. Host/port/path options are propagated to the
underlying FastMCP settings, with ``--mount-path`` only used by the SSE run
mode.
