# Python Standards

Standards for all Punt Labs Python projects. This document is the canonical reference — individual project CLAUDE.md files should reference it, not duplicate it.

Current Python projects: Biff, Quarry, LangLearn TTS.

---

## Toolchain

| Tool | Purpose | Command |
|------|---------|---------|
| **uv** | Package manager, virtualenv, task runner | `uv sync`, `uv run`, `uv build`, `uv publish` |
| **ruff** | Linting and formatting | `uv run ruff check .`, `uv run ruff format .` |
| **mypy** | Type checking (strict) | `uv run mypy src/ tests/` |
| **pyright** | Type checking (strict, second opinion) | `uv run pyright src/ tests/` |
| **pytest** | Testing | `uv run pytest` |
| **typer** + **rich** | CLI framework | — |
| **FastMCP** | MCP server framework | — |

## Python Version

Target **3.13+**. Use modern PEP conventions:
- `from __future__ import annotations` in every file
- `X | Y` unions (not `Union[X, Y]`)
- `Annotated` for metadata
- `type` statements where appropriate

## Quality Gates

Run before every commit. All must pass with zero violations.

```bash
uv run ruff check .                    # Lint
uv run ruff format --check .           # Format check
uv run mypy src/ tests/                # Type check (strict)
uv run pyright src/ tests/             # Type check (strict)
uv run pytest                          # All tests pass
```

Build validation (before release):

```bash
uv build
uvx twine check dist/*
```

## Style

- **Double quotes.** Line length 88. Enforced by ruff.
- All imports at top of file, grouped per PEP 8 (stdlib, third-party, local).
- No inline imports.

## Types

- Full type annotations on every function signature and return type.
- mypy strict mode and pyright strict mode. Zero errors.
- Never `Any` unless interfacing with untyped third-party libraries. Document why with inline type-ignore comments.
- `@dataclass(frozen=True)` for immutable value types. Pydantic models with immutability for validated data.
- Use `Protocol` classes for abstractions and third-party libraries without stubs.
- `cast()` in string form for ruff TC006: `cast("list[str]", x)`.
- `py.typed` marker in every package.

## Prohibited Patterns

- **No `hasattr()`** — use protocols and structural typing.
- **No `Any` without documented reason** and inline type-ignore comment.
- **No backwards-compatibility shims.** When code changes, callers change. No `_old_name = new_name` aliases, no `# removed` tombstones, no re-exports of dead symbols.
- **No runtime introspection** for type decisions. Use explicit protocol inheritance.
- **No mock objects in production code.**
- **No defensive coding or fallback logic** unless at a system boundary (user input, external API).

## Error Handling

- Fail fast. Raise exceptions on invalid input. No defensive fallbacks.
- No warning filters to hide problems. Fix root causes.
- `ValueError` for domain violations. Framework-specific exceptions (e.g., `click.ClickException`, `typer.Exit`) for CLI user errors.
- Never catch broad `Exception` unless re-raising or at a boundary (CLI entry point, MCP tool handler).

## Logging

- `logger = logging.getLogger(__name__)` per module.
- `logging.basicConfig()` configured once in CLI and server entry points.
- MCP server logs to stderr only (stdout reserved for stdio transport).

## Project Layout

```
<project>/
  pyproject.toml            # Package metadata, dependencies, tool config
  uv.lock                   # Locked dependencies
  src/<package>/
    __init__.py             # Version
    __main__.py             # CLI entry point
    py.typed                # PEP 561 marker
    cli.py                  # Typer app
    server.py               # FastMCP server
    ...
  tests/
    conftest.py             # Shared fixtures
    test_*.py               # Test modules mirror source
  CLAUDE.md                 # Project-specific instructions (references this doc)
  CHANGELOG.md              # Keep a Changelog format
  README.md                 # User-facing documentation
  .beads/                   # Issue tracking
```

## pyproject.toml

Required sections:

```toml
[project]
name = "<name>"                    # Matches CLI command, no -mcp suffix
version = "X.Y.Z"
description = "..."
requires-python = ">=3.13"
authors = [{ name = "...", email = "..." }]
license = { text = "MIT" }

[project.scripts]
<name> = "<package>.cli:app"       # CLI entry point
<name>-server = "<package>.server:run_server"  # MCP server entry point (if applicable)

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

## Testing

- Every module ships with tests. Untested code is unfinished code.
- Tests mirror source structure: `test_cli.py`, `test_server.py`, etc.
- If a test fails, fix it. Do not skip, ignore, or work around it.
- Integration tests requiring external services are marked with pytest markers (e.g., `@pytest.mark.integration`).

### Testing Pyramid

| Tier | What It Tests | Speed |
|------|---------------|-------|
| **1. Unit** | Tool logic, data models, pure functions | Fast (~1s) |
| **2. Integration** | MCP protocol, cross-component state | Medium (~2-5s) |
| **3. Subprocess/E2E** | Wire protocol, CLI args, process lifecycle | Slow (~5-10s) |
| **4. SDK** | End-to-end with Claude (optional, costs money) | Very slow (~30s) |

Default `pytest` runs tiers 1-2 only. Higher tiers are opt-in via markers.

## Distribution

1. Published to **PyPI** via `uv build && uvx twine upload dist/*`
2. Installable via `pip install <name>` or `uv tool install <name>`
3. Version in `pyproject.toml` is the single source of truth (except when plugin.json or manifest.json must match)

## Release Workflow

1. Bump version in `pyproject.toml` (and any mirrors: `plugin.json`, `manifest.json`, `__init__.py`)
2. Move `[Unreleased]` entries in `CHANGELOG.md` to new version section with date
3. Run all quality gates
4. Commit: `chore: release vX.Y.Z`
5. Build: `rm -rf dist/ && uv build && uvx twine check dist/*`
6. Upload to PyPI: `uvx twine upload dist/*`
7. Tag: `git tag vX.Y.Z`
8. Push: `git push origin main vX.Y.Z`
9. GitHub release: `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file -`
10. Verify: `uv tool install --upgrade <name> && <name> doctor`

A release is not complete until all 10 steps are done.

## Secrets

- API keys and credentials from environment variables only.
- No profiles, no `.env` files committed, no hardcoded keys.
- `doctor` verifies required secrets are available without printing them.
