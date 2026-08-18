# CLI Standards

Standards for command-line interfaces across all Punt Labs projects. Role models: **beads** (`bd`) and **entire** (`entire`).

---

## Core Principle

**The CLI is the complete product.** Every capability the engine offers must be
reachable from the terminal. The CLI is one client surface of the engine (see
the [Projection Model](architecture.md#the-projection-model-canonical)); MCP
tools, slash commands, and plugin hooks are peer clients, and they add nothing
the terminal cannot reach. This is why the CLI must expose every engine
capability as a command.

A user who never opens Claude Code can use every feature. A user inside Claude Code gets the same features surfaced through the plugin layer.

Projects that are inherently prompt-driven (e.g., Dungeon, where Claude *is* the game engine) are exempt.

---

## Command Layers

Organize subcommands into three layers. Product commands come first in `--help`.

### Layer 1: Product commands

The reason the tool exists. These are verbs that do the tool's core job.

```text
quarry search <query>        biff who              lux scene show <spec>
quarry ingest <path-or-url>  biff finger <user>    lux session ls
quarry explain <topic>       biff talk <user>      lux topic publish <t>
quarry sync                  biff write <user>     lux ping
```

Product commands are **noun-first** when the tool has more than one
kind of noun to act on — `lux scene show`, `lux session ls`,
`bd issue list` — and are a **single verb** when the tool has only one
noun (`quarry search`, `biff who`). Noun-first is the default at
scale; the single-verb form is reserved for genuinely single-noun
tools. Grouping by noun keeps related operations together in `--help`,
in library discovery, and in the MCP tool list, and lets the vocabulary
grow without renaming the surface.

Every MCP tool has a corresponding CLI command. Every slash command has a corresponding CLI command. Every REST route has a corresponding CLI command. Every library method has a corresponding CLI command. All four are thin clients of the same engine code — the CLI holds no logic the others lack.

**Assess omissions, not inclusions.** The default is equivalence: an operation on any surface is presumed to exist on every surface. An absence is a *considered exception* with a stated reason recorded in the project's design record, not a default. When reviewing surface coverage, list the omissions and demand justification for each; do not audit the inclusions.

**Admin verbs are CLI-only.** Operations that install, uninstall, enable, disable, or supervise the tool itself (`install`, `uninstall`, `enable`, `disable`, `doctor`, `mcp`, `hub install|uninstall|start|stop|restart|status`) are the admin tier. They appear on the CLI and nowhere else — an agent-turn is not a legitimate caller of a process-supervision verb. Exposing an admin verb on MCP recreates the superuser MCP surface the identity model forbids (see the reference lux epic `lux-0shg` and its DES-086 precedent for the invariant statement). The converse also holds: every MCP tool has a slash-command equivalent unless a considered exception is stated (e.g., non-blocking receive verbs, programmatic-only registrations).

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

| Language | Framework | Rationale |
|----------|-----------|-----------|
| Python | [typer](https://typer.tiangolo.com/) | Type-safe, minimal boilerplate, auto-completion |
| Go | [cobra](https://cobra.dev/) | Dominant Go CLI framework (kubectl, docker, gh). Typed flags, auto-help, subcommands, completion. |

### Entry point

**Python:** Every CLI defines its entry point in `<package>/__main__.py`:

```python
app = typer.Typer()
```

The `pyproject.toml` entry point is `<package>.__main__:app`. This makes `python -m <package>` work automatically.

**Go:** Every CLI defines its entry point in `cmd/<tool>/main.go`:

```go
package main

import "os"

func main() {
    if err := rootCmd.Execute(); err != nil {
        os.Exit(1)
    }
}
```

The root command is defined in a separate file (e.g., `root.go`) with persistent
flags. Running the binary without a subcommand prints help --- do not default to
a subcommand like `serve`.

### Help text

Help text is an agent interface, not just a human convenience. An AI agent
that discovers the CLI via `--help` must be able to determine every available
command, every flag, and the output format without trial and error. If help
text is vague or incomplete, the agent will hallucinate flags.

- One-line tagline on the Typer app: `<tool>: <what it does>`
- Plain text output --- disable typer's rich markup for help screens
- Per-command docstrings, imperative voice
- Product commands first, admin commands after
- Every flag must appear in `--help` with its type and default (if optional)
- The app-level help must document `--json` as a global flag (see Global Flags)

The same rule extends to operator-facing shell scripts (workspace `.bin/*.sh`, fleet rollouts, install helpers): a header + `Usage:` block + `--help` handler are mandatory. See [shell.md § Operational Safety](shell.md#operational-safety) for the shell-side details.

### Subcommand naming

Subcommands are **`noun verb`** for tools with more than one kind of
noun to act on (`lux scene show`, `lux session ls`, `bd issue list`),
and **single verbs** for tools with only one noun (`quarry search`,
`biff who`, `vox unmute`). Noun-first is the default at scale; the
single-verb form is reserved for genuinely single-noun tools.

Nouns are stable — they name what the engine holds (`scene`,
`session`, `issue`) — and verbs grow around them. Grouping by noun
means adding an operation adds a new verb under an existing noun, not
a new top-level command; the surface grows without reshuffling.

Arguments disambiguate, not subcommand names. `quarry ingest ./doc.pdf` and `quarry ingest https://example.com` are the same subcommand --- the tool infers the type from the input. Not `ingest-file` and `ingest-url`.

Exception: batch variants may use a suffix when the interface genuinely differs (e.g., `synthesize-batch` takes a JSON manifest file).

---

## Command Architecture

Every non-leaf project uses the **Humble Object Commands** pattern
(Pattern 2 below). Direct delegation (Pattern 1) is the exception,
reserved for projects with one client surface and no orchestration.
Any project that ships two or more client surfaces (CLI + MCP,
CLI + REST, etc.) uses the commands layer — otherwise the same
operation is written once per surface, and the surfaces drift.

See [Python standards](python.md#rules) for the language mechanics and
[Humble Object Commands](../patterns/humble-object-commands.md) for
the full pattern.

### Pattern 1: Direct Delegation (single-surface exception)

Each CLI command calls one core function and formats the result. Use
only when the project has one client surface and no shared
orchestration.

**Python:**

```python
@app.command()
def search(query: str) -> None:
    """Search the knowledge base."""
    results = quarry.search(query)
    for r in results:
        print(f"{r.score:.2f}  {r.title}")
```

**Go:**

```go
var searchCmd = &cobra.Command{
    Use:   "search <query>",
    Short: "Search the knowledge base",
    Args:  cobra.ExactArgs(1),
    RunE: func(cmd *cobra.Command, args []string) error {
        results, err := quarry.Search(args[0])
        if err != nil {
            return err
        }
        g.printResult(results, func() {
            for _, r := range results {
                fmt.Printf("%.2f  %s\n", r.Score, r.Title)
            }
        })
        return nil
    },
}
```

### Pattern 2: Humble Object Commands (default)

Every engine operation is a `@final` callable class in
`src/<package>/commands/`, exported as a module-level singleton the
four client adapters (CLI, MCP, REST, library) share. The class takes
a `Ctx` (collaborators) plus operation-specific arguments and returns
a `CommandResult`. The CLI wrapper interprets `text` and `exit_code`;
the MCP adapter JSON-encodes `json_data`; the REST adapter maps the
same envelope onto HTTP status; the library caller inspects fields
directly. Vox's `src/punt_vox/commands/voice.py` is the reference:

```python
# src/<package>/commands/_result.py
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandResult:
    text: str
    json_data: dict[str, object] | None = None
    error: bool = False
    exit_code: int = 0
```

```python
# src/<package>/commands/voice.py
from typing import Self, final


@final
class VoiceCommand:
    """List or set the session voice for the active provider."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def __call__(
        self, ctx: Ctx, name: str | None = None
    ) -> CommandResult:
        if name is None:
            return self._list(ctx)
        ctx.store.write_field("voice", name)
        return CommandResult(text=f"voice: {name}", json_data={"voice": name})


voice: VoiceCommand = VoiceCommand()
```

The class-per-verb shape is deliberate: it satisfies the OO ratchet
(behavior lives with the operation, not in a module-level function),
it composes cleanly with `Ctx` for dependency injection, and it lets
the four adapters share one instance without re-wrapping. The
module-level singleton (`voice: VoiceCommand = VoiceCommand()`) is
how each adapter reaches it — `from <package>.commands import voice`,
then `await voice(ctx, ...)`.

The CLI entry point uses a single `_run()` adapter for all plumbing:

```python
# src/<package>/__main__.py
def _run(coro_factory: Callable[[CliContext], Awaitable[CommandResult]]) -> None:
    async def _inner() -> None:
        async with cli_context() as ctx:
            result = await coro_factory(ctx)
            if json_output:
                print_json(
                    result.json_data if result.json_data is not None else result.text
                )
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

Projects with a `serve` command add one additional global flag:

| Flag | Short | Purpose |
|------|-------|---------|
| `--remote <url>` | | Use remote HTTP API instead of local execution (see Remote Mode) |

### `--json`

When set, all output is valid JSON written to stdout. Human-readable messages go to stderr or are suppressed. Errors are JSON objects: `{"error": "<message>"}`. List commands return JSON arrays; detail commands return JSON objects.

Pattern: `bd --json list`, `bd --json show <id>`.

### `--verbose` / `--quiet`

`--verbose` enables debug logging to stderr. `--quiet` suppresses everything except errors. They are mutually exclusive. Default is neither (normal output).

### Go: persistent flags

In cobra, global flags are **persistent flags** on the root command. They
propagate to all subcommands automatically --- no manual parsing in each handler.

```go
// globalOpts holds parsed global flags that apply to all subcommands.
type globalOpts struct {
    JSON    bool
    Verbose bool
    Quiet   bool
}

var g globalOpts

func init() {
    rootCmd.PersistentFlags().BoolVar(&g.JSON, "json", false, "JSON output")
    rootCmd.PersistentFlags().BoolVarP(&g.Verbose, "verbose", "v", false, "Debug logging")
    rootCmd.PersistentFlags().BoolVarP(&g.Quiet, "quiet", "q", false, "Errors only")
}
```

Global flags work in any position: `beadle-email --json contact list` and
`beadle-email contact list --json` are equivalent. Cobra handles this; hand-rolled
parsers typically do not.

### Go: output routing

Every Go CLI should have a `printResult` helper that branches on `--json`:

```go
func (g globalOpts) printResult(v any, humanFn func()) error {
    if g.JSON {
        data, err := json.MarshalIndent(v, "", "  ")
        if err != nil {
            return fmt.Errorf("marshal JSON: %w", err)
        }
        fmt.Println(string(data))
        return nil
    }
    if !g.Quiet {
        humanFn()
    }
    return nil
}
```

All commands call `g.printResult(data, humanFn)` --- never `json.Marshal` +
`fmt.Println` directly. This ensures `--json` and `--quiet` are respected
everywhere.

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

Toggle the tool in the current repository, per the
[Tool Enable/Disable Standard](tool-enable-disable.md). `enable` deposits
`.punt-labs/<tool>/` (user guide + `enabled` marker), adds the canonical
`@.punt-labs/<tool>/CLAUDE.md` import line to the repo `CLAUDE.md`, and may
register additive `.claude/settings.json` entries. `disable` removes the import
line, the marker, and the settings entries; the vendored directory stays
dormant. The enabled signal is the in-directory marker
`.punt-labs/<tool>/enabled` — not a repo-root dotfile.

Not every tool needs this. If the tool has no per-repo presence, omit it.

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

**Python:** Every CLI supports shell completion via typer's built-in `--install-completion` and `--show-completion`.

**Go:** Cobra generates completions via `rootCmd.GenBashCompletionV2`,
`rootCmd.GenZshCompletion`, and `rootCmd.GenFishCompletion`. Add a `completion`
subcommand:

```go
var completionCmd = &cobra.Command{
    Use:   "completion <bash|zsh|fish>",
    Short: "Generate shell completion script",
    Args:  cobra.ExactArgs(1),
    RunE: func(cmd *cobra.Command, args []string) error {
        switch args[0] {
        case "bash":
            return rootCmd.GenBashCompletionV2(os.Stdout, true)
        case "zsh":
            return rootCmd.GenZshCompletion(os.Stdout)
        case "fish":
            return rootCmd.GenFishCompletion(os.Stdout, true)
        default:
            return fmt.Errorf("unsupported shell: %s", args[0])
        }
    },
}
```

---

## Projection Strategy

Each surface is a thin client of the engine (see the
[Projection Model](architecture.md#the-projection-model-canonical)). The CLI
covers every engine capability; the other surfaces reach the same engine code:

| Surface | How it reaches the engine |
|---------|------------------------|
| **MCP tools** | Each MCP tool calls the same engine functions the CLI calls. |
| **Slash commands** | Each slash command maps to a CLI command. The command `.md` file instructs Claude to call the **MCP tool** (not Bash → CLI). |
| **Plugin hooks** | Hooks call `<tool> hook <event>` --- the CLI is the dispatcher. |

When adding a new capability, implement it in the engine and expose it through the CLI first (the completeness surface). Then wire the MCP server and slash commands to the same engine code. Never add a capability to the plugin that the terminal cannot reach.

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
   Simple and direct. Preferred for MCP, where the LLM rarely chains
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
