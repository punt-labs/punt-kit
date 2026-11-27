---
paths:
  - "**/*.py"
---

# Python Enablement, Integration and Permissions

**Introduced:** 2026-11-27

Implements the [tool enable/disable](../../standards/tool-enable-disable.md),
[integration](../../standards/integration.md) and
[permissions](../../standards/permissions.md) policies for tools written in
Python. Review gates mean the named evaluator checks the consuming tool's
code and tests for these cases; they do not claim punt-kit runs every tool's
tests.

## PY-TED-1: Write host files under the shared import contract

**Implements:** TED-1, TED-13, TED-14, TED-15 · **Gate:** `review` (enablement evaluator)

Read and write host files as bytes (or with `newline=""`) so no line ending
is translated. Hold `fcntl.flock(fd, LOCK_EX)` on the sibling
`.<host>.punt-import.lock` for the whole read-modify-write, write a
`tempfile.NamedTemporaryFile(dir=<host dir>, delete=False)`, then
`os.replace` it over `os.path.realpath(host)` with the original mode from
`os.stat`. Port `ClaudeMdImport` from `punt-labs/biff` for fence
classification and sorted insertion. Test LF, CRLF and lone-CR hosts, a
dangling fence, a symlinked host and two parallel writers.

## PY-TED-2: Implement scoped enable and disable

**Implements:** TED-5, TED-6, TED-7, TED-8, TED-9, TED-10, TED-11, TED-12, TED-17, TED-22, TED-23 · **Gate:** `review` (enablement evaluator)

Take the scope as a Typer option constrained to `project` or `local`. Before a
personal write or removal, resolve the target with `Path.resolve()` and run
`git check-ignore -q` and `git ls-files --error-unmatch` on it; refuse when
the target is not ignored or is tracked. Compare the new bytes with the file's
current bytes and skip the write when they are equal. Check the opt-out before
any write. Test repeated `enable` and `disable` with `git status --porcelain`
empty afterwards, enabling under an opt-out, and `--refresh` against an
unlisted occupied path.

## PY-TED-3: Merge settings entries in sorted position

**Implements:** TED-25, TED-26, TED-27, PERM-12, PERM-13, PERM-14, PERM-15, PERM-16, PERM-17, PERM-18, PERM-19, PERM-20, PERM-21, PERM-22 · **Gate:** `review` (permissions evaluator)

Load the settings file with `json.loads`, refuse a file that is not a JSON
object, and refuse a target whose resolved project directory is `$HOME`. For
each missing entry, insert it before the first existing entry that sorts
after it, or append; never sort or move existing entries. Remove by exact
value. Write under the sibling lock with the same atomic replace as
PY-TED-1, and only when an entry was added or removed. Render a tool-owned CI
workflow from a template and refuse to replace a file whose bytes are not the
tool's previous render.

## PY-TED-4: Decide effective state in one function

**Implements:** TED-21, TED-24, TED-37, INT-3 · **Gate:** `review` (enablement evaluator)

Expose one function that reads the shared marker, personal marker, opt-out and
personal `disabled` from the git root with `Path.exists()` and returns the
effective state and the deciding file. MCP tools, hooks, daemons, `status` and
peer presence checks call it; none re-derives the state. Test every row of
the TED-24 table.

## PY-TED-5: Keep the rest of the enablement contract

**Implements:** TED-2, TED-3, TED-4, TED-16, TED-18, TED-19, TED-20, TED-28, TED-29, TED-30, TED-31, TED-32, TED-33, TED-34, TED-35, TED-36 · **Gate:** `review` (enablement evaluator)

Ship the user guide as package data read with `importlib.resources`, never a
symlink into the installed package. Keep `enable` and `init` as separate
commands, and give the MCP enablement tool `action: Literal["enable",
"disable"]` and `scope: Literal["project", "local"] = "local"`. Keep personal
preferences in `*.local.*` files. `punt repo audit` implements TED-30.

## PY-INT-1: Integrate with peers without importing them

**Implements:** INT-1, INT-2, INT-4, INT-5, INT-6, INT-7, INT-8, INT-9, INT-10, INT-11, INT-12, INT-13, INT-14 · **Gate:** `review` (integration evaluator)

Declare hard dependencies in `pyproject.toml`. Discover a peer binary with
`shutil.which` behind `functools.cache`, at first use and never at import
time. Never import a peer's package to detect it. Read peer state files and
ethos extensions with `tomllib`, `yaml.safe_load` or `json`; never open one
for writing. Keep bundled integration code in its own module.

## PY-PERM-1: Scaffold and audit repo settings

**Implements:** PERM-1, PERM-2, PERM-3, PERM-4, PERM-5, PERM-6, PERM-7, PERM-8, PERM-9, PERM-10, PERM-11, PERM-23 · **Gate:** `punt repo audit`

`punt repo init` scaffolds `.claude/settings.json` with the baseline allow and
deny rules and removes dead path rules without rewriting them; `punt repo
audit` reports dead rules, missing deny rules, a missing `mcp__github__*`,
local paths in `settings.json` and an unignored `settings.local.json`.

## PY-PERM-2: Scope engine operations to the caller

**Implements:** PERM-24, PERM-25, PERM-26, PERM-27 · **Gate:** `review` (security evaluator)

Engine operations take the caller identity as a required argument and derive
store keys and ownership from it; no operation accepts an `owner=` override.
Register install, uninstall, service, `enable`, `disable` and `doctor` only
as CLI commands, never as MCP tools or REST routes.
