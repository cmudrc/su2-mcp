Quickstart
==========

Fast path
---------

If you want to get moving immediately, use this minimal setup:

.. code-block:: bash

   python3 -m venv .venv
   source .venv/bin/activate
   make dev
   su2-mcp --transport stdio

Then come back to the sections below for validation, examples, and workflow
details.

Setup
-----

Create a local virtual environment and install the development dependencies:

.. code-block:: bash

   python3 -m venv .venv
   source .venv/bin/activate
   make dev

Run the default quality gates:

.. code-block:: bash

   make test
   make ci

Start the server
----------------

Run the CLI over stdio:

.. code-block:: bash

   su2-mcp --transport stdio

Inspect a non-blocking HTTP configuration example:

.. code-block:: bash

   PYTHONPATH=src python3 examples/server/http_launch_config.py

Current capability notes
------------------------

- The default CI/examples path is deterministic and does not require SU2
  binaries.
- MCP tool names and request/response schemas remain stable.
- Real solver execution is optional and depends on `SU2_CFD`/`SU2_DEF`
  availability on PATH.
