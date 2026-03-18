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
quarry search <query>        biff who              vox unmute <text>
quarry ingest <path-or-url>  biff finger <user>    vox notify y/n/c
quarry explain <topic>       biff talk <user>      vox speak y/n
quarry sync                  biff write <user>     vox voice <name>
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
| `punt-labs/tts` | `punt-vox` | `pip install punt-vox` |
| `punt-labs/langlearn-tts` | `punt-langlearn-tts` | `pip install punt-langlearn-tts` |
| `punt-labs/punt-kit` | `punt-kit` | `pip install punt-kit` |

The prefix avoids name collisions on PyPI (no namespace mechanism like npm's `@org/pkg`) and makes org affiliation clear.

### CLI entry point names

CLI entry points use the **short name** (no prefix): `quarry`, `biff`, `vox`, `punt`. Users type the short name; the package name is only visible during install.

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

Help text is an agent interface, not just a human convenience. An AI agent
that discovers the CLI via `--help` must be able to determine every available
command, every flag, and the output format without trial and error. If help
text is vague or incomplete, the agent will hallucinate flags.

- One-line tagline on the Typer app: `<tool>: <what it does>`
- Plain text output --- disable typer's rich markup for help screens
- Per-command docstrings, imperative voice
- Product commands first, admin commands after
- Every flag must appear in `--help` with its default value and type
- The app-level help must document `--json` as a global flag (see Global Flags)

### Subcommand naming

Subcommands are **single verbs**: `search`, `ingest`, `explain`, `talk`, `write`.

Arguments disambiguate, not subcommand names. `quarry ingest ./doc.pdf` and `quarry ingest https://example.com` are the same subcommand --- the tool infers the type from the input. Not `ingest-file` and `ingest-url`.

Exception: batch variants may use a suffix when the interface genuinely differs (e.g., `synthesize-batch` takes a JSON manifest file).

---

## Command Architecture

CLI commands follow one of two patterns depending on complexity. See [Python standards](python.md#rules) for the decision criteria.

### Pattern 1: Direct Delegation

Each CLI command calls one core function and formats the result. This is the default for most projects.

```python
@app.command()
def search(query: str) -> None:
    """Search the knowledge base."""
    results = quarry.search(query)
    for r in results:
        print(f"{r.score:.2f}  {r.title}")
```

### Pattern 2: Humble Object Commands

When a CLI command orchestrates multiple core calls, manages session state, or formats composite results, extract the logic into a pure async function returning `CommandResult`:

```python
# src/<package>/commands/_result.py
@dataclass(frozen=True)
class CommandResult:
    text: str
    json_data: object | None = field(default=None)
    error: bool = False
```

```python
# src/<package>/commands/who.py
async def who(ctx: CliContext) -> CommandResult:
    sessions = await ctx.relay.get_sessions()
    return CommandResult(text=format_who(sessions), json_data=[...])
```

The CLI entry point uses a single `_run()` adapter for all plumbing:

```python
# src/<package>/__main__.py
def _run(coro_factory: Callable[[CliContext], Awaitable[CommandResult]]) -> None:
    async def _inner() -> None:
        async with cli_context() as ctx:
            result = await coro_factory(ctx)
            if json_output:
                print_json(result.json_data if result.json_data is not None else result.text)
            elif result.error:
                print(result.text, file=sys.stderr)
            else:
                print(result.text)
            if result.error:
                raise typer.Exit(code=1)
    asyncio.run(_inner())

@app.command()
def who() -> None:
    _run(commands.who)

@app.command()
def finger(user: Annotated[str, typer.Argument(...)]) -> None:
    _run(lambda ctx: commands.finger(ctx, user))
```

`_run()` owns the context lifecycle, JSON/text branching, and exit codes. Command functions are pure — no I/O, no `sys.exit`, no framework imports.

### `CommandResult` specification

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `text` | `str` | (required) | Human-readable output |
| `json_data` | `object` | `None` | JSON-serializable payload; `None` means use `text` |
| `error` | `bool` | `False` | `True` → exit code 1 in CLI, inspectable in library |

**Validation stays at the boundary.** CLI parses strings (`on/off`) into typed values (`bool`) before calling the command function. Command functions accept typed parameters, not raw CLI strings.

See [Humble Object Commands](../patterns/humble-object-commands.md) for the full pattern.

---

## Global Flags

Every CLI supports these global flags, following beads:

| Flag | Short | Purpose |
|------|-------|---------|
| `--json` | | JSON output for every command |
| `--verbose` | `-v` | Debug logging |
| `--quiet` | `-q` | Errors only (suppress non-essential output) |
| `--help` | `-h` | Show help |
| `--remote <url>` | | Use remote HTTP API instead of local execution (only for projects with `serve`) |

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
| vox | Current provider, voice, vibe, character usage |

### `install`

Machine-scoped setup --- run once per machine to register the MCP server, download models, or create global data directories.

### `enable` / `disable`

Project-scoped activation, following entire's pattern. Toggle the tool in the current repository. Creates/removes a config file at the repo root (e.g., `.biff`, `.quarry`).

Not every tool needs this. If the tool has no per-repo state, omit it.

### `serve` / `mcp`

Start the MCP server. Required for projects that expose MCP tools. `serve` for HTTP transport, `mcp` for stdio transport.

---

## Remote Mode

If a project has a `serve` command that exposes an HTTP API, the CLI should
also be able to **consume** that API as an alternative to local execution. This
enables agents and humans to operate on remote instances without MCP overhead.

### The pattern

CLIs like `vercel`, `fly`, and `gh` are local binaries that operate on remote
services. The user runs a local command; the CLI handles auth, serialization,
and HTTP under the hood. Our CLIs talk to remote APIs (ElevenLabs, OpenAI
embeddings, AWS), but core logic runs locally. We lack a pattern where
`quarry find "query"` could transparently hit a remote Quarry instance ---
even though Quarry runs on Fly.io for the chat widget.

### `--remote <url>`

Projects with a `serve` command should accept a `--remote <url>` global flag
that switches the transport from local execution to the remote HTTP API:

```bash
# Local (default) --- runs against local LanceDB
quarry find "semantic search"

# Remote --- hits quarry.fly.dev HTTP API
quarry --remote https://quarry.fly.dev find "semantic search"
```

When `--remote` is set:

- All commands that have a corresponding REST endpoint delegate to HTTP
  instead of calling the library directly
- Auth is handled via an API key in an environment variable
  (`<TOOL>_API_KEY`) or a config file
- `--json` output is identical regardless of local or remote execution
- Commands that have no remote equivalent (e.g., `install`, `doctor`) exit
  non-zero with an error formatted according to the current output mode:
  plain text by default, `{"error": "<command> is not available in remote mode"}`
  when `--json` is set

### Implementation

The library already has the HTTP client (the `serve` command exposes it) and
the CLI already has the local call path. Remote mode adds a transport switch:

```python
def _get_client(remote: str | None) -> QuarryClient:
    if remote:
        api_key = os.environ.get("QUARRY_API_KEY")
        if not api_key:
            raise typer.BadParameter(
                "QUARRY_API_KEY environment variable is required for --remote"
            )
        return RemoteClient(url=remote, api_key=api_key)
    return LocalClient(db_path=default_db_path())
```

Both `LocalClient` and `RemoteClient` implement the same interface. CLI
commands call the client without knowing the transport.

### When to add remote mode

Not every project needs this. Add it when:

- The project has a `serve` command with a stable HTTP API
- There is a deployed remote instance that users or agents need to reach
- The alternative would be configuring an MCP proxy for remote access

Current candidates: **quarry** (Fly.io deployment exists).

---

## Hook Architecture

See **[hooks.md](hooks.md)** for the full hook standard, including Claude
Code's state machine, event patterns, the decision-block pattern, workflow
gates, common bugs, and the audit checklist.

Summary of the three-layer dispatch pattern:

1. **hooks.json** — registration (what events, what matchers)
2. **Shell script** — thin gate (check config, pass stdin)
3. **CLI handler** — business logic (`<tool> hook <event>`)

Shell scripts fail-open on observation (`|| true`), fail-closed on
mutation (propagate errors). Business logic lives in `hooks.py` as
testable pure functions.

---

## Shell Completion

Every CLI supports shell completion via typer's built-in `--install-completion` and `--show-completion`.

---

## Projection Strategy

The CLI is the source of truth. Other surfaces project it:

| Surface | How it projects the CLI |
|---------|------------------------|
| **MCP tools** | Each MCP tool wraps a CLI capability. The MCP server calls the same functions the CLI calls. |
| **Slash commands** | Each slash command maps to a CLI command. The command `.md` file instructs Claude to call the **MCP tool** (not Bash → CLI). |
| **Plugin hooks** | Hooks call `<tool> hook <event>` --- the CLI is the dispatcher. |

When adding a new capability, implement it in the CLI first. Then project it to the MCP server and slash commands. Never add a capability to the plugin that the CLI cannot do.

### Call path performance

Two fast paths exist for plugin operations. Choose based on who initiates:

```text
Model-initiated:    LLM ──► MCP server (persistent, structured)
Event-driven:       Hook ──► CLI (no LLM, direct execution)
```

| Path | Avg latency | Use when |
|------|------------|----------|
| **LLM → MCP tool** | ~3.2s | Model initiates: synthesis, queries, config changes. Persistent stdio server — zero startup cost. |
| **Hook → CLI** | ~110ms | Event-driven: stop notifications, chimes, signal tracking. No model round-trip. |
| ~~LLM → Bash → CLI~~ | ~4.6s | **Avoid.** Combines model round-trip + process spawn. Use only when no MCP tool exists. |
| ~~LLM → Read/Write~~ | — | **Never.** Couples the model to file format details, bypasses validation. |

**Rule:** Slash commands call MCP tools. Hooks call CLI. The model never
touches config files directly — use the MCP or CLI layer.

---

## Sync vs Async

The core question is not "sync or async" as a library property — it is **"does
the caller need the return value to proceed?"** The answer depends on both the
operation type and the projection surface.

### Operation types

| Type | Caller needs result? | Examples |
|------|---------------------|----------|
| **Query** | Yes — the result IS the point | `search`, `status`, `list`, `show` |
| **Transform** | Yes — the output IS the point | `encode`, `convert`, `export` |
| **Side-effect** | No — confirmation is nice, not essential | `ingest`, `speak`, `send`, `delete`, `sync` |

### Surface behavior

| Surface | Process lifetime | Implication |
|---------|-----------------|-------------|
| **CLI** | Ephemeral (exits) | Must wait — needs exit code |
| **MCP** | Long-lived (server) | Can fire-and-forget side-effects |
| **REST** | Long-lived (server) | Can 202 + poll for side-effects |

### Decision tree

```text
Does the caller need the return value to proceed?
├── YES (query / transform)
│   └── Block on all surfaces. No choice.
│
└── NO (side-effect)
    ├── CLI   → Block anyway. Process must exit with correct code.
    ├── MCP   → Fire-and-forget. Return optimistic result immediately.
    │           Background thread does the real work.
    └── REST  → 202 Accepted + job ID. Client polls or gets webhook.
```

### MCP fire-and-forget pattern

For side-effect MCP tools, return predicted metadata immediately and process
in a background thread:

```python
# Predict what the result will be (paths, status, metadata)
predicted = _predict_results(requests, provider, dir_path)

# Do the real work in a background thread
threading.Thread(
    target=_process,
    args=(requests, provider, dir_path),
    daemon=True,
).start()

# Return immediately — caller doesn't wait for I/O
return json.dumps([result_to_dict(r) for r in predicted])
```

The daemon thread ensures cleanup on server exit. The predicted result gives
the caller enough information to continue (file paths, voice names, status
fields) without waiting for network calls, encoding, or disk writes.

Reference implementation: `vox/src/punt_vox/server.py`.

### Eventual consistency

Side-effects processed in background threads create eventual consistency.
If the caller ingests a document and immediately searches for it, the search
may return stale results. Two options:

1. **Documented eventual consistency** — caller knows results may lag.
   Simple and honest. Preferred for MCP, where the LLM rarely chains
   side-effect → query in the same turn.

2. **Completion signal** — background thread updates a status field or emits
   a log entry. Caller can check if it needs to.

Prefer option 1 unless the operation has a strong chain-then-query pattern.

### Library determines the ceiling

The library's concurrency model sets the upper bound:

| Library | CLI | MCP | REST |
|---------|-----|-----|------|
| **Async-native** (biff/NATS) | `asyncio.run()` | Native async handlers | Native async routes |
| **Sync + I/O-heavy** (vox/ElevenLabs) | Sync call, wait | Fire-and-forget thread | 202 + thread |
| **Sync + fast** (quarry/LanceDB reads) | Sync call, wait | Sync return | Sync response |
| **Sync + slow side-effects** (quarry/ingest) | Sync call, wait | Fire-and-forget thread | 202 + thread |

A sync library can still have non-blocking MCP tools — wrap the blocking call
in `threading.Thread(daemon=True)`. An async library gets this naturally.

### Per-project summary

| Project | Library style | MCP queries | MCP side-effects |
|---------|--------------|-------------|-----------------|
| **quarry** | Sync (LanceDB) | Block (search, list) | Should fire-and-forget (ingest, sync) |
| **biff** | Async (NATS) | Await (who, finger, read) | Could fire-and-forget (write, wall) |
| **vox** | Sync (ElevenLabs) | Block (status, who) | Fire-and-forget (unmute, record) |
| **langlearn-tts** | Sync (delegates to vox) | Block (status) | Should fire-and-forget (synthesize) |
| **punt-kit** | Sync (local ops) | Block (all ops are queries) | N/A |

### Projection by architecture

How CLI and MCP reach core logic depends on whether the project uses direct delegation or a commands layer:

**Direct delegation** (quarry): Both CLI and MCP call core functions directly. No commands layer exists — each surface is a thin adapter over the same library calls.

```text
CLI  ──▶ quarry.search(query)
MCP  ──▶ quarry.search(query)
Lib  ──▶ quarry.search(query)
```

**Commands layer** (biff): CLI calls `_run(commands.X)`. MCP tools may call core functions directly (when the orchestration differs) or reuse command functions. Library consumers import command functions.

```text
CLI  ──▶ _run(commands.who)   ──▶ relay.get_sessions()
MCP  ──▶ relay.get_sessions()    (MCP tools call core directly)
Lib  ──▶ commands.who(ctx)    ──▶ relay.get_sessions()
```

The commands layer gives library consumers the same orchestrated behavior as the CLI without going through CLI plumbing.
