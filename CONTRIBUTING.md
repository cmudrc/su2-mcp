# Contributing to `su2-mcp`

Thanks for improving the project.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
make dev
```

The `dev` extra installs linting, formatting, typing, testing, docs, packaging,
and pre-commit tooling.

## Local Quality Checks

Run these before opening a pull request:

```bash
make fmt
make lint
make type
make test
make docs
```

Optional but recommended:

```bash
pre-commit install
pre-commit run --all-files
```

## Pull Request Guidelines

- Keep changes focused.
- Add or update tests for behavior changes.
- Update docs and examples when user-facing workflows change.
- Describe what changed and how you validated it.

## Code Style

- Python 3.12+ target.
- Ruff for formatting and linting.
- Mypy for static type checking.
- Pytest for tests.

## Current Capability Boundaries

- The default test suite validates deterministic local session/config/results flows
  without requiring SU2 binaries.
- Real SU2 integration tests should stay optional and use the `integration_real`
  marker once stable fixture assets are available.
