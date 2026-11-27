---
paths:
  - "**/*.go"
---

# Go Enablement, Hooks, Integration and Permissions

**Introduced:** 2026-11-27

Implements the [tool enable/disable](../../standards/tool-enable-disable.md),
[hook](../../standards/hooks.md), [integration](../../standards/integration.md)
and [permissions](../../standards/permissions.md) policies for tools written
in Go. The named evaluator reviews the consuming tool's code and tests for
these cases; this file does not imply that punt-kit executes Go tests.

## GO-TED-1: Write host files under the shared import contract

**Implements:** TED-1, TED-13, TED-14, TED-15 · **Gate:** `review` (enablement evaluator)

Read host files with `os.ReadFile` and never translate line endings. Hold
`syscall.Flock(fd, syscall.LOCK_EX)` on the sibling
`.<host>.punt-import.lock` for the whole read-modify-write, write
`os.CreateTemp` in the host's directory, `Chmod` it to the original mode and
`os.Rename` it over `filepath.EvalSymlinks(host)`. Test LF, CRLF and lone-CR
hosts, a dangling fence, a symlinked host and two parallel writers.

## GO-TED-2: Implement scoped enable and disable

**Implements:** TED-5, TED-6, TED-7, TED-8, TED-9, TED-10, TED-11, TED-12, TED-17, TED-22, TED-23 · **Gate:** `review` (enablement evaluator)

Take the scope as a flag validated to `project` or `local`. Before a personal
write or removal, resolve the target with `filepath.EvalSymlinks` and run
`git check-ignore -q` and `git ls-files --error-unmatch` on it; refuse when the
target is not ignored or is tracked. Use `bytes.Equal` against the current
file and skip the write when nothing changes. Check the opt-out before any
write. Test repeated `enable` and `disable` with `git status --porcelain`
empty afterwards.

## GO-TED-3: Merge settings entries in sorted position

**Implements:** TED-25, TED-26, TED-27, PERM-12, PERM-13, PERM-14, PERM-15, PERM-16, PERM-17, PERM-18, PERM-19, PERM-20, PERM-21, PERM-22 · **Gate:** `review` (permissions evaluator)

Decode the settings file into `map[string]any`, refuse a file that is not a
JSON object, and refuse a target whose resolved project directory is the home
directory. Insert each missing entry before the first existing entry that
sorts after it, or append; never sort or move existing entries. Remove by
exact value, and write under the sibling lock with the atomic replace of
GO-TED-1 only when an entry changed. Refuse to replace a CI workflow whose
bytes are not the tool's previous render.

## GO-TED-4: Decide effective state in one function

**Implements:** TED-21, TED-24, TED-37, INT-3 · **Gate:** `review` (enablement evaluator)

Expose one function that stats the shared marker, personal marker, opt-out and
personal `disabled` at the git root and returns the effective state and the
deciding file. MCP tools, hooks, daemons, `status` and peer presence checks
call it. Test every row of the TED-24 table.

## GO-TED-5: Keep the rest of the enablement contract

**Implements:** TED-2, TED-3, TED-4, TED-16, TED-18, TED-19, TED-20, TED-28, TED-29, TED-30, TED-31, TED-32, TED-33, TED-34, TED-35, TED-36 · **Gate:** `review` (enablement evaluator)

Ship the user guide with `embed.FS`. Keep `enable` and `init` as separate
commands, and give the MCP enablement tool an `action` enum of `enable` and
`disable` and a `scope` enum of `project` and `local`, default `local`. Keep
personal preferences in `*.local.*` files.

## GO-HOOK-1: Keep hook handlers pure and fast

**Implements:** HOOK-1, HOOK-2, HOOK-6, HOOK-7, HOOK-9, HOOK-25 · **Gate:** `review` (hook evaluator)

Handlers take the decoded payload struct and return the output struct; they
recover from panics and return an empty result. Start side effects with
`exec.Cmd.Start` and do not `Wait`. Expose handlers as a hidden `hook`
subcommand, and keep network clients and stores out of the hook path's
initialization.

## GO-HOOK-2: Read stdin with a deadline

**Implements:** HOOK-8 · **Gate:** `review` (hook evaluator)

Read hook stdin with `os.Stdin.SetReadDeadline` and a short timeout, taking
the bytes available; never `io.ReadAll(os.Stdin)` without a deadline. Test
with a pipe whose writer stays open.

## GO-HOOK-3: Gate, wire, register and test hooks

**Implements:** HOOK-3, HOOK-4, HOOK-5, HOOK-10, HOOK-11, HOOK-12, HOOK-13, HOOK-14, HOOK-15, HOOK-16, HOOK-17, HOOK-18, HOOK-19, HOOK-20, HOOK-21, HOOK-22, HOOK-23, HOOK-24 · **Gate:** `review` (hook evaluator)

Every handler has a shell gate that calls it and a `hooks.json` entry. Deny
with `permissionDecisionReason`, and check `stop_hook_active` before a Stop
hook blocks. Table-test each handler, and test the gate end to end with JSON
on stdin.

## GO-INT-1: Integrate with peers without importing them

**Implements:** INT-1, INT-2, INT-4, INT-5, INT-6, INT-7, INT-8, INT-10, INT-11, INT-12, INT-13, INT-14 · **Gate:** `review` (integration evaluator)

Declare hard dependencies in `go.mod`. Discover a peer binary with
`exec.LookPath` behind `sync.Once`, at first use. Never import a peer's module
to detect it, and open peer state files read-only.

## GO-PERM-1: Write repo settings to the baseline

**Implements:** PERM-1, PERM-2, PERM-3, PERM-4, PERM-5, PERM-6, PERM-7, PERM-8, PERM-9, PERM-10, PERM-11, PERM-23 · **Gate:** `review` (permissions evaluator)

A Go tool that writes `.claude/settings.json` or `settings.local.json` writes
only `Read(path)` and `Edit(path)` path rules, plugin-scoped `Skill()` values
and its own MCP wildcard, and never removes a baseline or deny rule.

## GO-PERM-2: Scope engine operations to the caller

**Implements:** PERM-24, PERM-25, PERM-26, PERM-27 · **Gate:** `review` (security evaluator)

Engine operations take the caller identity as a required parameter and derive
store keys and ownership from it; no operation accepts an owner override.
Register admin verbs only as CLI commands.
