# Python CLI Rules

**Introduced:** 2026-11-24

These rules implement the [CLI standard](../../standards/cli.md), including its
applicability and named subsets.

## PY-CLI-1: Register the canonical command tree with Typer

**Implements:** CLI-1, CLI-2, CLI-3, CLI-4, CLI-5, CLI-6, CLI-7, CLI-11, CLI-13 · **Gate:** review (Python CLI reviewer)

Use the Typer entry point described in
[Python Package Architecture](python-package-architecture.md#pl-pa-5-cli-framework).
Register resource groups with `add_typer` and leaf handlers with `command`.
Compare the registration to the approved command map, including setup
ownership and documented exceptions. Register `version` as a command, not
an eager version option. Configure `-h` alongside `--help` on full-contract
apps. Register the root callback with `invoke_without_command=True`; when
`ctx.invoked_subcommand is None`, print `ctx.get_help()` and exit
successfully on the default no-argument path. Test bare invocation and
explicit help separately
via `CliRunner`; only dispatch a different bare action when the approved
command map specifies it, and never dispatch to a service. Use Typer's
`--install-completion` and `--show-completion` for shell completion.
`--show-completion` writes the script without a JSON wrapper (CLI-11).

## PY-CLI-2: Adapt command results at the CLI boundary

**Implements:** CLI-8, CLI-9, CLI-10, CLI-18 · **Gate:** review (Python CLI reviewer)

Register diagnostics and supported MCP launch commands as adapters. Use the
shared Commands Layer where it applies
([PL-PA-3](python-package-architecture.md#pl-pa-3-commands-layer)); have the
CLI turn the result into stdout, stderr, and a `typer.Exit` code without
adding product logic. Compare the documented stopping point with the actual
return path in command tests, using a fake backend that can distinguish
acceptance from completion. When shipping a separate hook executable,
register its entry point separately in `pyproject.toml` and check that
public CLI help does not list it.

## PY-CLI-3: Parse global output options and serialize once

**Implements:** CLI-11, CLI-12 · **Gate:** review (Python CLI reviewer)

Collect root options in the Typer callback; where Typer does not inherit
options after the command path, reuse the option definitions at the leaf
and merge explicit settings without resetting root values with leaf defaults.
Use one result formatter for the JSON value; send logs and Rich progress to
stderr. With `CliRunner`, check root and leaf flag positions against the
same command, parse all of stdout as one value, and assert the exit code and
stream separation for success and failure.

## PY-CLI-4: Share remote selection between CLI and integrations

**Implements:** CLI-14, CLI-15, CLI-16, CLI-17 · **Gate:** review (Python CLI reviewer)

Pass the parsed Typer option into the client resolver used by command
handlers; keep environment handling in that resolver so hook and MCP
processes that construct clients without a CLI invocation can also select
the endpoint. Test precedence with isolated environment and config fixtures,
and use a fake client to verify the selected target, trust and credential
sources, rejection of unsupported operations, and diagnostics for retired
settings. Include an explicit loopback URL in the test matrix to distinguish
a tunnel from default local discovery.
