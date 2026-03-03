# Python Standards

Standards for all Punt Labs Python projects. This document is the canonical reference — individual project CLAUDE.md files should reference it, not duplicate it.

Current Python projects: punt-kit, Biff, Quarry, LangLearn TTS, LangLearn, LangLearn Types, LangLearn Anki, LangLearn Imagegen.

---

## Package Architecture

Punt Labs Python packages expose **three interfaces** — a Python library, a CLI, and an MCP server. The library is the core; CLI and MCP are thin frontends to it.

Simple projects delegate directly from CLI/MCP to core functions. Complex projects add a **commands layer** between CLI and core when individual commands orchestrate multiple core calls.

```text
Direct delegation (quarry):        Commands layer (biff):

┌─────────┐   ┌─────────┐         ┌─────────┐   ┌─────────┐
│   CLI   │   │   MCP   │         │   CLI   │   │   MCP   │
└────┬────┘   └────┬────┘         └────┬────┘   └────┬────┘
     │             │                   │             │
     ▼             ▼                   ▼             ▼
┌───────────────────────┐         ┌────────────┐    │
│     Library Layer     │         │  Commands  │    │
│ (core, types, protos) │         │ (pure fns) │    │
└───────────────────────┘         └─────┬──────┘    │
                                        │           │
                                        ▼           ▼
                                  ┌───────────────────────┐
                                  │     Library Layer     │
                                  │ (core, types, protos) │
                                  └───────────────────────┘
```

### Rules

1. **`__init__.py` is the public API.** Export core functions, classes, and types via an explicit `__all__`. Consumers should be able to `from <package> import ...` and get useful work done without touching CLI or MCP.

2. **Core logic lives in dedicated modules** (`core.py`, `database.py`, `pipeline.py`, etc.) that never import from `cli.py` or `server.py`. The dependency arrow always points inward: CLI → core, MCP → core, never the reverse.

3. **Types and protocols in their own modules.** `types.py` or a `types/` package for dataclasses, `Protocol` classes, and type aliases. These are importable without pulling in heavy dependencies.

4. **CLI and MCP are thin.** `cli.py` parses arguments, calls core functions, formats output. `server.py` registers MCP tools, calls core functions, returns results. Neither contains business logic.

5. **Extract commands when CLI orchestrates.** When a CLI command does more than delegate to one core function — combining multiple calls, managing session state, or formatting composite results — extract it to a `commands/` package as a pure async function returning `CommandResult`. Use `CommandResult(error=True, ...)` for expected user-facing failures (invalid input, missing resources, service errors) that should be reported cleanly. Programmer errors and violated invariants still raise exceptions per the Error Handling section. See [Humble Object Commands](../patterns/humble-object-commands.md).

### When to add a commands layer

| Signal | Architecture |
|--------|-------------|
| Each CLI command maps to one core function | **Direct delegation** — no commands layer needed |
| CLI commands combine multiple core calls, manage sessions, or format composite output | **Commands layer** — extract to `commands/` |
| MCP tools and CLI commands share orchestration logic | **Commands layer** — both surfaces call command functions |
| MCP tools call core directly while CLI has its own orchestration | **Commands layer** for CLI only; MCP stays thin |

Most projects start with direct delegation and never need more. Add the commands layer when the CLI grows beyond simple dispatch.

### Reference: direct delegation

Quarry is the gold standard for direct delegation:

```python
# quarry/__init__.py — the public library API
from quarry.collections import derive_collection
from quarry.config import Settings, load_settings
from quarry.database import get_db, search
from quarry.pipeline import ingest_content, ingest_document, ingest_url

__all__ = [
    "Settings",
    "derive_collection",
    "get_db",
    "ingest_content",
    "ingest_document",
    "ingest_url",
    "load_settings",
    "search",
]
```

A downstream Python app can `from quarry import search, get_db` and run queries without any CLI or MCP dependency.

### Reference: commands layer

Biff is the reference for the commands pattern (see [DES-022](https://github.com/punt-labs/biff/blob/main/DESIGN.md)):

```python
# biff/commands/__init__.py — command functions as library API
from biff.commands._result import CommandResult
from biff.commands.who import who
from biff.commands.finger import finger
from biff.commands.wall import wall

__all__ = ["CommandResult", "who", "finger", "wall", ...]
```

A downstream Python app can `from biff.commands import who, CommandResult` and invoke commands without CLI plumbing.

### Exceptions

- **Pure contract libraries** (e.g., `langlearn-types`) have no CLI or MCP — they export only protocols and dataclasses. This is correct; the tri-modal rule applies to packages that contain logic.
- **Internal tooling** (e.g., `punt-kit`) is not a shipping library. The library API standard applies to products, not build tools.

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

```text
<project>/
  pyproject.toml            # Package metadata, dependencies, tool config
  uv.lock                   # Locked dependencies
  src/<package>/
    __init__.py             # Public API (__all__, re-exports from core modules)
    __main__.py             # CLI entry point
    py.typed                # PEP 561 marker
    cli.py                  # Typer app (thin — delegates to core)
    server.py               # FastMCP server (thin — delegates to core)
    core.py                 # Core logic (or split across domain modules)
    types.py                # Protocols, dataclasses, type aliases
    commands/               # (optional) Command functions — see Rule 5
      __init__.py           #   Re-exports command functions
      _result.py            #   CommandResult dataclass
      <command>.py           #   One module per command
    ...
  tests/
    conftest.py             # Shared fixtures
    test_*.py               # Test modules mirror source
    test_commands/          # (if commands/ exists) One test file per command
  CLAUDE.md                 # Project-specific instructions (references this doc)
  CHANGELOG.md              # Keep a Changelog format
  README.md                 # User-facing documentation
  .beads/                   # Issue tracking
```

## pyproject.toml

Required sections:

```toml
[project]
name = "punt-<name>"               # PyPI uses punt- prefix (see Naming below)
version = "X.Y.Z"
description = "..."
requires-python = ">=3.13"
authors = [{ name = "...", email = "..." }]
license = { text = "MIT" }

[project.urls]
Homepage = "https://github.com/punt-labs/<repo>"
Repository = "https://github.com/punt-labs/<repo>"
"Bug Tracker" = "https://github.com/punt-labs/<repo>/issues"

[project.scripts]
<name> = "<package>.cli:app"       # CLI entry point uses short name (no prefix)
<name>-server = "<package>.server:run_server"  # MCP server entry point (if applicable)

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### Naming

PyPI has no namespace mechanism (unlike npm's `@org/pkg`), so all packages use the **`punt-`** prefix to avoid collisions and signal org affiliation. CLI entry points use the **short name** — users type `quarry`, not `punt-quarry`.

| Repo | PyPI package | CLI command | Python import |
|------|-------------|-------------|---------------|
| `punt-labs/quarry` | `punt-quarry` | `quarry` | `quarry` |
| `punt-labs/biff` | `punt-biff` | `biff` | `biff` |
| `punt-labs/langlearn` | `punt-langlearn` | `langlearn` | `langlearn` |
| `punt-labs/langlearn-tts` | `punt-langlearn-tts` | `langlearn-tts` | `langlearn_tts` |
| `punt-labs/langlearn-anki` | `punt-langlearn-anki` | `langlearn-anki` | `langlearn_anki` |
| `punt-labs/langlearn-imagegen` | `punt-langlearn-imagegen` | `langlearn-imagegen` | `langlearn_imagegen` |
| `punt-labs/langlearn-types` | `punt-langlearn-types` | — | `langlearn_types` |
| `punt-labs/punt-kit` | `punt-kit` | `punt` | `punt_kit` |

The full naming convention is in [CLI Standards](cli.md#naming-and-distribution).

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

### Humble Object Testing

When a project uses the [commands layer](#rules), command functions are testable without mocks, subprocesses, or network:

1. **Construct context** with an in-memory protocol implementation (e.g., `LocalRelay(tmp_path)` instead of `NatsRelay`).
2. **Call the command function** directly: `result = await who(ctx)`.
3. **Assert on result fields**: `result.text`, `result.json_data`, `result.error`.

This runs in milliseconds and covers the full command logic. Reserve subprocess and E2E tests for wire protocol and process lifecycle concerns.

See [Humble Object Commands](../patterns/humble-object-commands.md) for the full pattern.

## Distribution

### PyPI

1. Published to **PyPI** via automated `release.yml` workflow (see Release Workflow below)
2. Installable via `pip install punt-<name>` or `uv tool install punt-<name>`
3. Version in `pyproject.toml` is the single source of truth (except when plugin.json or manifest.json must match)
4. `[project.urls]` must include Homepage, Repository, and Bug Tracker pointing to the `punt-labs` GitHub org

### .mcpb bundles

MCP server projects also distribute as `.mcpb` bundles for Claude Desktop. The bundle is built during the release workflow and attached to the GitHub release as a download artifact. The `manifest.json` at the repo root defines the bundle metadata, including the PyPI package name and MCP server configuration.

### CLI tools

CLI-only tools (like `punt-kit`) install via `pip install` or `uv tool install` and register a console script entry point. No `.mcpb` bundle needed.

## Release Workflow

Releases are automated via `release.yml`. A tag push (`v*`) triggers the full pipeline:

```text
build → testpypi → test-install → pypi
```

1. **build** — `uv build` + `uvx twine check dist/*`, uploads artifact
2. **testpypi** — Publishes to TestPyPI via trusted publishing (OIDC)
3. **test-install** — Installs the package from TestPyPI and verifies the CLI entry point
4. **pypi** — Publishes to production PyPI via trusted publishing (OIDC)

TestPyPI failure blocks PyPI publish. This catches packaging issues before they reach production.

### Developer steps

1. Bump version in `pyproject.toml` (and any mirrors: `plugin.json`, `manifest.json`, `__init__.py`)
2. Move `[Unreleased]` entries in `CHANGELOG.md` to new version section with date
3. Run all quality gates
4. Commit: `chore: release vX.Y.Z`
5. Tag and push: `git tag vX.Y.Z && git push origin main vX.Y.Z`
6. CI handles build, TestPyPI, install verification, and PyPI upload
7. Create GitHub release: `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file -`
8. Verify: `uv tool install --upgrade punt-<name> && <name> --version`

### Trusted publishing setup (one-time per package)

Authentication uses [trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) — no tokens or secrets needed. Configure each package on both pypi.org and test.pypi.org:

- Owner: `punt-labs`
- Repository: `<repo-name>`
- Workflow: `release.yml`
- Environment: `release` (PyPI) or `testpypi` (TestPyPI)

This is a manual step in the PyPI/TestPyPI web UI. See [GitHub standards](github.md) for workflow details.

## Secrets

- API keys and credentials from environment variables only.
- No profiles, no `.env` files committed, no hardcoded keys.
- `doctor` verifies required secrets are available without printing them.
