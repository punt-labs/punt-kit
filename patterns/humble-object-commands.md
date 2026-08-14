# Humble Object Commands

## Problem

CLI commands that orchestrate multiple core calls accumulate infrastructure concerns — relay lifecycle, JSON/text branching, exit codes, stdout/stderr routing. When these live inside `@app.command()` functions, the command logic becomes untestable without mocking the infrastructure, uncallable from library code, and duplicated across every command.

## Forces

- Commands must be testable without network, subprocess, or mocks.
- Commands must be importable as a library API for downstream Python consumers.
- The CLI framework (typer) owns argument parsing and help text — that wiring must remain visible.
- MCP tools may call core functions directly rather than reusing CLI commands, because MCP has its own output channel.
- Exit codes, JSON output, and stderr routing are CLI concerns, not command logic.

## Solution

Apply the Humble Object pattern: separate testable command logic from untestable CLI plumbing.

### CommandResult

A frozen dataclass returned by every command function:

```python
@dataclass(frozen=True)
class CommandResult:
    text: str  # Human-readable output
    json_data: object | None = field(default=None)  # JSON payload; None means use text
    error: bool = False  # True → exit code 1 in CLI
```

Commands return expected user-facing errors as `CommandResult(text="User not found", error=True)` rather than raising. This keeps error paths testable with `assert result.error` instead of `pytest.raises`. Programmer errors and violated invariants still raise exceptions.

### Command functions

Each command is a pure async function in `commands/<name>.py`:

```python
async def who(ctx: CliContext) -> CommandResult:
    sessions = await ctx.relay.get_sessions()
    if not sessions:
        return CommandResult(text="No sessions.", json_data=[])
    return CommandResult(
        text=format_who(sessions),
        json_data=[s.to_dict() for s in sessions],
    )
```

No I/O, no exit codes, no framework imports. The function takes a context and returns a result.

### `_run()` adapter

A single function in `__main__.py` handles all CLI plumbing:

```python
def _run(coro_factory: Callable[[CliContext], Awaitable[CommandResult]]) -> None:
    async def _inner() -> None:
        async with cli_context() as ctx:
            result = await coro_factory(ctx)
            if json_output:
                data = result.json_data if result.json_data is not None else result.text
                print_json(data)
            elif result.error:
                print(result.text, file=sys.stderr)
            else:
                print(result.text)
            if result.error:
                raise typer.Exit(code=1)

    asyncio.run(_inner())
```

Typer commands become one-liners:

```python
@app.command()
def who() -> None:
    _run(commands.who)


@app.command()
def finger(user: Annotated[str, typer.Argument(...)]) -> None:
    _run(lambda ctx: commands.finger(ctx, user))
```

### Protocol widening

The context's core dependency (e.g., relay, database client) must be typed as a `Protocol`, not a concrete class. This is the key change that enables testing:

```python
class Relay(Protocol):
    async def get_sessions(self) -> list[Session]: ...
    async def send_message(self, to: str, message: str) -> None: ...


@dataclass
class CliContext:
    relay: Relay  # Not NatsRelay — accepts any implementation
    user: str
    ...
```

Tests inject an in-memory implementation (`LocalRelay(tmp_path)`) that satisfies the protocol without network, mocks, or external services.

## Consequences

- **Testable.** Command functions run in milliseconds with no mocks and no network. Assert on `result.text`, `result.json_data`, `result.error`.
- **Library API.** Downstream Python code can `from <package>.commands import who, CommandResult` and invoke commands directly.
- **No duplication.** `_run()` is written once; adding a new command requires only the command function and a one-liner in `__main__.py`.
- **Validation at the boundary.** CLI parses strings (`on/off`) into typed values (`bool`) before calling command functions. Command functions accept typed parameters.
- **MCP independence.** MCP tools can call core functions directly or reuse command functions — the pattern does not force MCP through the commands layer.

## When to Use

Use the commands layer when CLI commands orchestrate multiple core calls, manage session state, or format composite results. If each CLI command maps to one core function, [direct delegation](../standards/python.md#rules) is simpler and sufficient.

## Related Patterns

- [Two-Channel Display](two-channel-display.md) — Commands that produce data tables need the two-channel split (panel summary + model-emitted full output). `CommandResult.text` maps naturally to the `additionalContext` channel.
- [Doctor Checks](doctor-checks.md) — The `doctor` command itself follows the Humble Object pattern: each check is a pure function returning pass/fail, and the CLI runner formats the results.

## Known Uses

- **Biff** ([DES-022](https://github.com/punt-labs/biff/blob/main/DESIGN.md)) — 10 commands (`who`, `finger`, `write`, `read`, `plan`, `last`, `wall`, `mesg`, `tty`, `status`) extracted to `src/biff/commands/`. 71 tests, 100% line coverage, 0.15s runtime. `LocalRelay` + `WtmpRelay` provide in-memory protocol implementations.
