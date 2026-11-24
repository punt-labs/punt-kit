# CLI Standards

**Updated:** 2026-11-24

This standard governs the public command-line contract: what users and scripts
can invoke, where commands act, and what their results mean.

## Applicability

The full contract applies to Punt Labs developer tools, including emerging
tools and z-spec. They expose `version`, `doctor`, `status`, and `install`.
Pharo tools are excluded. The following named subsets are exhaustive for
those entry points:

- **Transport-only MCP bridge (mcp-proxy):** CLI-1 and CLI-8 only. For CLI-8,
  expose the bridge's health check; the subsection's `doctor` and `status`
  commands are not required.
- **Crypt game suite (`crypt`, `cryptd`, `crypt-admin`):** CLI-1 and CLI-5
  only, on each binary.

Internal hook dispatchers are governed by CLI-10 rather than the public
command contract. Operator-facing shell scripts follow the
[shell standard](shell.md#operational-safety).

## Clauses

### CLI-1: Expose one canonical version command

**Applies to:** python, go

`<tool> version` prints one plain stdout line, `<name> <semver>`, by default
and exits successfully. Do not provide `--version`, `-V`, or other version
aliases. Full-contract tools also support explicit JSON mode under CLI-11.

### CLI-2: Group product operations by noun

**Applies to:** python, go

Use `<tool> <noun> <verb>` by default. A noun names an independently
addressable resource; the same noun (for example, `mission`) must mean the
same basic thing across tools. Reuse established verbs for equivalent
operations, such as `list` for enumerating resources. Record a reason for
every exception, including a bare product verb in a genuinely single-noun
tool or a top-level command such as `doctor` that has no resource operand.

### CLI-3: Give each operation one unambiguous spelling

**Applies to:** python, go

Do not keep superseded commands or options as backward-compatibility aliases.
Use a positional argument for a required operand, an option for a modifier or
an explicit discriminator, and stdin for piped content when supported.
Infer an operand's type only when its forms can be distinguished safely;
otherwise provide an explicit choice. A separate batch command needs a
distinct contract, such as manifest input and per-item results, not merely a
different spelling for the same operation.

### CLI-4: Approve each command map before migration

**Applies to:** python, go

Before migrating a tool, obtain Jim's approval of its command map: the
public command tree, argument and option forms, shared noun meanings, and
reasons for any exceptions. Keep the approved map in the product's design
record, not in this standard.

### CLI-5: Provide working root help

**Applies to:** python, go

`<tool> --help` prints usage to stdout and exits successfully without
performing work or requiring a running service.

### CLI-6: Make the public interface discoverable

**Applies to:** python, go

For full-contract tools, provide `-h` as shorthand for `--help` and help at
every public command path. Show a short purpose, usage, operands, public
options and their value types and defaults, and how to discover the output
contract. List product commands before diagnostics, setup, and service
management. Document global flags at the root. Keep internal hook
dispatchers out of the public command list.

### CLI-7: Apply the platform's naming and setup boundaries

**Applies to:** python, go

Follow [Naming](naming.md) for binaries and packages and
[Distribution](distribution.md) for installation and registration.
Document the product-to-binary mapping when the repository and entry points
differ. Expose machine setup as `install`; repository integration is a
separate operation governed by
[Tool Enable/Disable](tool-enable-disable.md#23-the-enable--disable-convention).

### CLI-8: Distinguish installation health from operating state

**Applies to:** python, go

`doctor` checks installation health. Report pass or fail for applicable
dependencies, versions, integrations, and connectivity; fail if a required
check fails. `status` reports current operating state rather than repeating
installation checks. A transport-only bridge's required health check
reports reachability of its selected target.

### CLI-9: Project product capabilities without exposing administration

**Applies to:** python, go

Apply the [canonical projection model](architecture.md#the-projection-model-canonical)
to the CLI. Equivalent product capabilities use consistent names; parity is
judged by capability, not by counting routes or library methods. Record and
justify omissions in the product's design record. Installation and process
supervision are CLI-only. Expose `mcp` for an MCP stdio entry point and
`serve` for a network MCP entry point when those transports are supported.
A network MCP listener does not by itself make a remote product API.

### CLI-10: Keep hook dispatch internal

**Applies to:** python, go

Follow [Hooks](hooks.md) for invocation, payload, and performance contracts.
A tool can use an internal `<tool> hook` dispatcher or a split
`<tool>-hook` binary where startup time or memory footprint warrants it.
Do not require the same dispatcher to be exposed through both paths.

### CLI-11: Give every finite public command a JSON result mode

**Applies to:** python, go

Support `--json` on every public command that runs and exits with a result,
including setup actions such as `enable` and `install` that only confirm
success. In JSON mode write exactly one JSON value to stdout, including on
failure; use an array for a list, an object for a detail or action result, and
an object containing an `error` string for failure. Send progress and
diagnostic messages to stderr or suppress them. Never accept `--json` and
print prose instead. Keep exit status meaningful in either mode.

Protocol streams and servers (such as `mcp` and `serve`), live interactive
sessions and TUIs (such as live `call`, `talk`, and `ui`), hook dispatch,
and host-owned output contracts such as statusline text are exempt when
they do not exit with a command result or own stdout for another contract.
Shell completion generators that write a script to stdout also follow
the shell's artifact format rather than the JSON result contract.
A guided command that exits with an outcome is not exempt merely because
it takes time or prints progress.

### CLI-12: Honor global output flags consistently

**Applies to:** python, go

Use normal output by default. `--verbose` / `-v` enables diagnostic logging
on stderr; `--quiet` / `-q` suppresses nonessential output. They are mutually
exclusive. Quiet mode does not suppress a requested JSON result. Accept
applicable global output flags before and after the command path with the
same effect. Do not let diagnostics contaminate protocol or result stdout.

### CLI-13: Provide shell completion

**Applies to:** python, go

Provide a documented way to obtain shell completion generated from the
public command tree, so suggestions track the supported paths and options.

### CLI-14: Select a remote product instance explicitly

**Applies to:** python, go

A full-contract tool that supports remote product execution must accept
`--remote <url>` and `<TOOL>_REMOTE`, with the flag taking precedence over
the environment variable and both overriding a saved default or local
discovery. Use the uppercase tool name with hyphens replaced by underscores.
Document the supported URLs and precedence. This applies to selecting another
instance of the product, not to selecting an upstream service, relay, local
socket, or MCP transport. Full-contract tools are expected to support remote
execution eventually; the selector requirement applies when that capability
exists, not simply when a tool gains a listener.

### CLI-15: Keep credentials and trust separate from remote selection

**Applies to:** python, go

The remote URL selects an endpoint only. Supply credentials and trust through
separate configuration, not through the URL. For an explicit target, do not
fall back to a local token, even when its URL points to loopback through a
tunnel. Document how to authenticate and establish trust for a selected
endpoint.

### CLI-16: Honor the target or report an unsupported operation

**Applies to:** python, go

Run applicable commands, including operational status, against the selected
instance and preserve their output contract across targets. A command that
cannot operate on an explicitly requested remote target must fail rather
than fall back to local execution. Local service management commands (such
as local start, stop, and restart) reject `--remote`.

### CLI-17: Make remote-selector cutovers explicit

**Applies to:** python, go

Remove superseded selector variables rather than accepting them as aliases.
`doctor` warns when a retired variable remains set. Update setup and
invocation documentation, including environment examples such as
`.envrc`, and tell operators to update their environment and restart any
long-lived MCP processes that inherited the old configuration.

### CLI-18: Define what success means for each command

**Applies to:** python, go

Exit zero means the work was successfully accepted or successfully performed.
Document which of those a command promises at the noun–verb level and what
its result proves. When acceptance is the boundary, describe the receipt
and any supported way to observe later progress or failure. For example,
a task ID can mean indexing was queued, a playback acknowledgement need not
mean the audio finished, and accepting scene state need not mean the display
has drawn it. Neither blocking nor a `--no-wait` switch is a general rule.
