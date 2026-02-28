# CLI Standards

Standards for command-line interfaces across all Punt Labs projects. Role models: **beads** (`bd`) and **entire** (`entire`).

---

## Core Principle

**The CLI is the complete product.** Every capability the tool offers is accessible from the terminal. MCP tools, slash commands, and plugin hooks are projections of CLI functionality --- they do not add capabilities the CLI lacks.

A user who never opens Claude Code can use every feature. A user inside Claude Code gets the same features surfaced through the plugin layer.

Projects that are inherently prompt-driven (e.g., Dungeon, where Claude *is* the game engine) are exempt.

---

## Command Layers

Organize subcommands into three layers. Product commands come first in `--help`.

### Layer 1: Product commands

The reason the tool exists. These are verbs that do the tool's core job.

```text
quarry search <query>        biff who              tts say <text>
quarry ingest <path-or-url>  biff finger <user>    tts speak on/off
quarry explain <topic>       biff talk <user>      tts vibe <mood>
quarry sync                  biff write <user>     tts voice <name>
```

Every MCP tool has a corresponding CLI command. Every slash command has a corresponding CLI command. The CLI command is the source of truth; the MCP tool and slash command call it or mirror its logic.

### Layer 2: Admin commands

Setup, health, and lifecycle. Universal across all CLIs.

| Subcommand | Purpose | Required? |
|-----------|---------|-----------|
| `version` | Print the version | Yes |
| `doctor` | Check installation health | Yes |
| `status` | Current state summary | Yes |
| `install` | Machine-scoped setup (MCP registration, models, data dirs) | Yes |
| `enable` / `disable` | Toggle the tool in the current project | If repo-scoped |
| `serve` | Start the MCP server | If MCP project |

### Layer 3: Hook dispatcher (internal)

Called by shell hook scripts, not by users. Hidden or de-emphasized in `--help`.

```text
<tool> hook <event>          # Claude Code lifecycle hooks
<tool> hook git <event>      # Git lifecycle hooks (if applicable)
```

Shell scripts are thin gates (check config, pass stdin). Business logic lives in Python as testable pure functions in a `hooks.py` module. The CLI subcommand is the bridge.

Pattern: `entire hooks <agent> <event>` --- "Commands called by hooks. These are internal and not for direct user use."

---

## Naming and Distribution

### PyPI package names

All packages use the `punt-` prefix on PyPI:

| Repo | PyPI package | Install command |
|------|-------------|-----------------|
| `punt-labs/quarry` | `punt-quarry` | `pip install punt-quarry` |
| `punt-labs/biff` | `punt-biff` | `pip install punt-biff` |
| `punt-labs/tts` | `punt-tts` | `pip install punt-tts` |
| `punt-labs/langlearn-tts` | `punt-langlearn-tts` | `pip install punt-langlearn-tts` |
| `punt-labs/punt-kit` | `punt-kit` | `pip install punt-kit` |

The prefix avoids name collisions on PyPI (no namespace mechanism like npm's `@org/pkg`) and makes org affiliation clear.

### CLI entry point names

CLI entry points use the **short name** (no prefix): `quarry`, `biff`, `tts`, `punt`. Users type the short name; the package name is only visible during install.

---

## Structure

### Framework

**typer** for all Python CLIs. typer wraps click and provides type-safe argument parsing with minimal boilerplate.

### Entry point

Every CLI defines its entry point in `<package>/__main__.py`:

```python
app = typer.Typer()
```

The `pyproject.toml` entry point is `<package>.__main__:app`. This makes `python -m <package>` work automatically.

### Help text

- One-line tagline on the Typer app: `<tool>: <what it does>`
- Plain text output --- disable typer's rich markup for help screens
- Per-command docstrings, imperative voice
- Product commands first, admin commands after

### Subcommand naming

Subcommands are **single verbs**: `search`, `ingest`, `explain`, `talk`, `write`.

Arguments disambiguate, not subcommand names. `quarry ingest ./doc.pdf` and `quarry ingest https://example.com` are the same subcommand --- the tool infers the type from the input. Not `ingest-file` and `ingest-url`.

Exception: batch variants may use a suffix when the interface genuinely differs (e.g., `synthesize-batch` takes a JSON manifest file).

---

## Global Flags

Every CLI supports these global flags, following beads:

| Flag | Short | Purpose |
|------|-------|---------|
| `--json` | | JSON output for every command |
| `--verbose` | `-v` | Debug logging |
| `--quiet` | `-q` | Errors only (suppress non-essential output) |
| `--help` | `-h` | Show help |

### `--json`

When set, all output is valid JSON written to stdout. Human-readable messages go to stderr or are suppressed. Errors are JSON objects: `{"error": "<message>"}`. List commands return JSON arrays; detail commands return JSON objects.

Pattern: `bd --json list`, `bd --json show <id>`.

### `--verbose` / `--quiet`

`--verbose` enables debug logging to stderr. `--quiet` suppresses everything except errors. They are mutually exclusive. Default is neither (normal output).

---

## Required Subcommands

### `version`

Print the version and exit. `<tool> version`, not `--version`.

Output format: `<name> <semver>`.

```text
$ biff version
biff 0.12.1

$ quarry version
quarry 0.10.1
```

### `doctor`

Check installation health --- pass/fail per dependency. Every project with external dependencies must have this.

The doctor command checks:

- Required binaries found and executable
- Required libraries/packages installed
- Correct versions where applicable
- Plugin registration (for Claude Code plugins)
- MCP server configuration (for MCP projects)
- Network connectivity (for projects with relay/API dependencies)

The installer should run `doctor` as its final step.

### `status`

Current state summary --- what the tool knows right now. Not health (that's `doctor`), but operational state.

| Tool | `status` shows |
|------|---------------|
| quarry | Active database, document count, registered directories, model info |
| biff | Connection state, active sessions, pending messages |
| tts | Current provider, voice, vibe, character usage |

### `install`

Machine-scoped setup --- run once per machine to register the MCP server, download models, or create global data directories.

### `enable` / `disable`

Project-scoped activation, following entire's pattern. Toggle the tool in the current repository. Creates/removes a config file at the repo root (e.g., `.biff`, `.quarry`).

Not every tool needs this. If the tool has no per-repo state, omit it.

### `serve` / `mcp`

Start the MCP server. Required for projects that expose MCP tools. `serve` for HTTP transport, `mcp` for stdio transport.

---

## Hook Architecture

### Principle

Hooks are plumbing, not product. They integrate the CLI with Claude Code's lifecycle but do not contain business logic themselves.

### Structure

```text
hooks/
  hooks.json              # Hook event registrations
  session-start.sh        # Thin shell gate -> <tool> hook session-start
  suppress-output.sh      # Output suppression for MCP tool calls

src/<package>/
  hooks.py                # Pure handler functions (testable)
  __main__.py             # CLI entry point, includes hook subcommands
```

### Shell scripts are thin gates

Shell scripts check preconditions (config file exists, tool is enabled) and delegate to the CLI:

```bash
#!/usr/bin/env bash
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[[ -f "$REPO_ROOT/.biff" ]] || exit 0
biff hook post-bash 2>/dev/null || true
```

### Python handlers are pure functions

Business logic lives in `hooks.py` as functions that take structured input and return structured output:

```python
def handle_post_bash(data: dict[str, Any]) -> str | None:
    """PostToolUse Bash -- detect events and return context."""
    ...
```

The CLI subcommand reads stdin, calls the handler, and writes output.

### Fail-open on observation, fail-closed on mutation

Following entire's pattern:

- Hooks that **observe** (PostToolUse, SessionStart) use `|| true` --- if the tool crashes, Claude Code continues normally.
- Hooks that **mutate** (PreToolUse that blocks execution) fail closed to preserve safety.

---

## Shell Completion

Every CLI supports shell completion via typer's built-in `--install-completion` and `--show-completion`.

---

## Projection Strategy

The CLI is the source of truth. Other surfaces project it:

| Surface | How it projects the CLI |
|---------|------------------------|
| **MCP tools** | Each MCP tool wraps a CLI capability. The MCP server calls the same functions the CLI calls. |
| **Slash commands** | Each slash command maps to a CLI command. The command `.md` file instructs Claude to call the corresponding MCP tool or CLI command. |
| **Plugin hooks** | Hooks call `<tool> hook <event>` --- the CLI is the dispatcher. |

When adding a new capability, implement it in the CLI first. Then project it to the MCP server and slash commands. Never add a capability to the plugin that the CLI cannot do.
