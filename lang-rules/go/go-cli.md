# Go CLI Rules

**Introduced:** 2026-11-24

These rules implement the [CLI standard](../../standards/cli.md), including its
applicability and named subsets.

## GO-CLI-1: Register the canonical command tree in the entry point

**Implements:** CLI-1, CLI-2, CLI-3, CLI-4, CLI-5, CLI-6, CLI-7, CLI-11, CLI-13 · **Gate:** review (Go CLI reviewer)

Compare the registered paths under `cmd/<binary>` with the approved command
map, including setup ownership and documented exceptions. With Cobra,
attach commands with `AddCommand` and write `version` explicitly rather than
setting `cobra.Command.Version`, which generates a flag. Use Cobra's
generated help and completion support, arranging command groups in public
help order. Use Cobra's root help path for bare invocation unless the
approved command map specifies a different default; do not dispatch to a
service. Check bare invocation, explicit help, version, and completion
with command tests. Check that Cobra's completion script reaches stdout
unchanged, without a JSON wrapper (CLI-11). Handwritten parsers must provide
the same contract.

## GO-CLI-2: Keep command handlers at the boundary

**Implements:** CLI-8, CLI-9, CLI-10, CLI-18 · **Gate:** review (Go CLI reviewer)

Dispatch from the command handler to the shared implementation, and return
the handler's error to the executable entry point for exit-code mapping.
Test diagnostic and command result paths against a fake service that
distinguishes acceptance from completion. For split hook binaries, use a
separate `cmd/<tool>-hook` entry point and verify the public parser does not
expose internal dispatch paths.

## GO-CLI-3: Bind global output flags and use one encoder

**Implements:** CLI-11, CLI-12 · **Gate:** review (Go CLI reviewer)

In Cobra, bind global output flags using root `PersistentFlags` and inspect
their settings before dispatch. Pass result and diagnostic writers into the
formatter separately (for example, `OutOrStdout` and `ErrOrStderr`). Use
one `encoding/json` encoder for the result in JSON mode. Exercise effective
flag positions, exit status, and stdout/stderr in table-driven command tests;
decoding the result and then reaching EOF checks for stray output.

## GO-CLI-4: Resolve remote options before dispatch

**Implements:** CLI-14, CLI-15, CLI-16, CLI-17 · **Gate:** review (Go CLI reviewer)

Bind the remote URL option at the root of a Cobra app and resolve it with
the environment and configured defaults before constructing the product
client. Pass the chosen endpoint separately from credentials and transport
trust settings. Test precedence, explicit loopback, local-only rejection,
and retired-variable diagnostics with controlled environment and client
fixtures, without contacting a production service.
