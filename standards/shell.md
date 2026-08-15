# Shell Script Standards

Standards for shell scripts across all Punt Labs projects. Shell scripts appear in every project type — install scripts, CI helpers, hooks, build scripts, infrastructure automation. These standards apply cross-cutting to any `.sh` file in any repo.

---

## Toolchain

| Tool | Purpose | Command |
|------|---------|---------|
| **shellcheck** | Static analysis | `shellcheck <file>` |
| **bash** | Target shell | Scripts must target bash 3.2+ (macOS default) or specify a newer version |

## Quality Gate

```bash
shellcheck scripts/*.sh hooks/*.sh *.sh
```

Adjust the glob to match where `.sh` files live in the project. The gate applies to every project that contains `.sh` files, regardless of project type.

Zero warnings, zero errors. No `# shellcheck disable` without a comment explaining why.

## Script Conventions

### Shebang

Use `#!/usr/bin/env bash` — not `#!/bin/bash`, not `#!/bin/sh`. Exception: install scripts use `#!/bin/sh` for POSIX portability (see Cross-Platform Install Scripts).

### Strict mode

Every script must start with:

```bash
#!/usr/bin/env bash
set -euo pipefail
```

| Flag | Effect |
|------|--------|
| `-e` | Exit on error |
| `-u` | Error on undefined variables |
| `-o pipefail` | Propagate pipe failures |

### Quoting

- Always double-quote variable expansions: `"$var"`, `"${array[@]}"`.
- Always quote command substitutions: `"$(command)"` not `$(command)`.
- Shellcheck enforces this (SC2086, SC2046).

### Functions

- Define functions before calling them (SC2218).
- Use `local` for function-scoped variables.
- Prefer `snake_case` for function and variable names.

### Error handling

- `cd` must always have a fallback: `cd "$dir" || exit 1`.
- Check command existence before use: `command -v tool >/dev/null 2>&1 || { printf '%s\n' "tool not found"; exit 1; }`.
- Under `set -eu`, subcommands that may fail must be wrapped in `if !` guards so failures produce error messages instead of silent script death: `if ! "$BINARY" install; then fail "Install failed"; fi`.
- Use `printf` over `echo` for portable output. Never use variables in `printf` format strings (SC2059).

### Style

- Indent with 2 spaces (consistent with Google Shell Style Guide).
- Max line length: 120 characters.
- Use `[[ ]]` for conditionals (not `[ ]`).
- Use `$(command)` for command substitution (not backticks).

## Operational Safety

Shell scripts that operators run directly — cross-repo workspace scripts, install helpers, fleet rollouts — are an agent interface just as much as a Python CLI. Apply the same discipline: a header that explains what runs and how, a `--help` handler, no destructive default, and a per-target ledger for anything that iterates.

The four rules below apply to every `.sh` file in `.bin/` and to any other operator-facing shell script. They do not apply to hook scripts (thin gates called by lifecycle events; see [hooks.md](hooks.md)) or to `install.sh` (covered by *Cross-Platform Install Scripts* below).

### Header contract

Every script must open with a one-line purpose comment followed by a `Usage:` block. A reader must be able to tell what the script does and how to run it from the first ten lines.

```bash
#!/usr/bin/env bash
# Purpose: single-sentence description of what the script does.
# Usage: script-name.sh [--dry-run] [--skip repo] [--apply]
#
# Optional expanded explanation of behavior, safety, and side effects.
set -euo pipefail
```

### `--help` handler

Every script that takes arguments must respond to `--help`/`-h` by printing usage and exiting `0`. Zero-arg invocation of a script that *requires* args (e.g. `resolve-threads.sh <branch>`) must also print usage — never error with an unhelpful shell trace, never fall through to real work.

Zero-arg invocation of a script that *accepts* an optional `--apply` (the destructive-scripts-default-to-preview pattern below) is not the same case: zero-arg means "preview" and exits `0` on its own path, NOT via the help handler. Do not conflate the two.

Convention for both:

```bash
usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--apply]
  --dry-run  Preview changes without applying (default).
  --apply    Apply changes.
EOF
}

# All scripts: respond to --help/-h.
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

# Scripts that REQUIRE args add this after the case:
#   if [ $# -eq 0 ]; then usage; exit 0; fi
# Scripts that ACCEPT --apply (preview-by-default) omit that guard —
# zero-arg falls through to the preview loop.
```

### Destructive scripts default to preview

Any script that mutates state — git write (`commit`, `push`, `checkout`, `branch`, `tag`, `reset`), filesystem write outside `.tmp/`, network POST/PATCH/DELETE (`gh api -X POST`, `curl -X PATCH`), `launchctl bootstrap/kickstart/bootout`, or `security add/delete-generic-password` — must EITHER:

- **Require a positional target argument.** `resolve-threads.sh <branch>` and `cascade-commit.sh <file>` are the pattern: no argument, no work.
- **Accept `--apply` with `--dry-run` as the implicit default.** Zero-arg invocation shows what would happen and exits `0`. `--apply` runs the mutation.

The pattern this replaces: `--dry-run=false` by default, so an unadorned `.bin/envrc-gitignore-rollout.sh` opens a PR-per-repo on any invocation. That surprised operators; it surprises agents more. The muscle-memory cost of the flip is worth it.

Use `--apply` for repeatable rollout/settings scripts. Use `--yes` for one-shot destructive operations (e.g. `depot-sync.sh` clears wheels then rebuilds). Do not mix — pick per file, stay consistent per category.

### Per-target outcome ledger

Scripts that iterate over multiple targets (child repos, PRs, files) must emit one line per target to stdout with the outcome and reason:

```text
ok    biff       branch pushed
skip  quarry     safety: dirty working tree
fail  vox        gh api: 422
```

Rollout-class scripts additionally write `.tmp/<script>-status.json` with the same information, so a follow-up invocation or a health-check module can inspect what happened. `envrc-canonical-rollout.sh --report` is the reference implementation; the ledger is not opt-in — a silent skip is a bug regardless of exit code.

The rule: an operator or agent reading the last screen of output must be able to tell whether each target succeeded, was skipped intentionally, or failed. `Done.` without per-target detail is a script bug.

## Cross-Platform Install Scripts

Projects that ship an `install.sh` must also ship an `install.ps1` for Windows (PowerShell). This follows the pattern established by Claude Code, Bun, and Deno.

### The dual installer pattern

| Platform | Script | User runs |
|----------|--------|-----------|
| macOS / Linux | `install.sh` | `curl -fsSL https://example.com/install.sh \| bash` |
| Windows | `install.ps1` | `irm https://example.com/install.ps1 \| iex` |

### install.sh conventions

- Target `/bin/sh` (POSIX), not bash — install scripts run on the widest range of systems.
- Shebang: `#!/bin/sh` (exception to the bash-first rule above).
- Shellcheck with `--shell=sh` to enforce POSIX compliance.
- Avoid bash 4+ features (associative arrays, `mapfile`, `${var,,}`). macOS ships bash 3.2.

### Stdin protection in piped scripts

When a script runs via `curl | sh`, stdin is the pipe — not a terminal. Any
child process that reads from stdin consumes bytes from the pipe, silently
truncating the script. The shell sees EOF and exits 0.

Commands that consume stdin: `claude` (any subcommand), `ssh`, `read`, `cat`
(no args), `docker run -i`, any interactive CLI tool.

**Rule**: Every command that may read from stdin must have `< /dev/null`:

```sh
claude plugin install "$PLUGIN" < /dev/null
ssh -n -o BatchMode=yes -T git@github.com 2>&1 | grep -q "authenticated"
```

For `ssh`, use `-n` (idiomatic equivalent of `< /dev/null`).

**Testing**: Always test install scripts via `curl | sh`, not `sh install.sh`.
Direct execution uses a terminal for stdin and does not reproduce the failure.

See DES-006 in DESIGN.md for the full root cause analysis.

### install.ps1 conventions

- Use `$ErrorActionPreference = 'Stop'` at the top (equivalent of `set -e`).
- Download with `Invoke-RestMethod` (aliased as `irm`).
- Test with PowerShell 5.1 (ships with Windows 10) and PowerShell 7+.

### Fallback (acceptable interim)

If `install.ps1` is not yet implemented, the project README must document the manual Windows installation path (e.g., `pip install`, `npm install`). This is acceptable as a temporary state — the install.ps1 should be tracked as a bead.

### Developer-facing scripts

Build scripts, CI helpers, hooks, and other developer-facing `.sh` files do not need a `.ps1` companion. These target bash and assume a Unix development environment.

---

## CI Integration

Projects with `.sh` files should include shellcheck in their lint CI workflow. Add as a step in the existing `lint.yml`:

```yaml
- name: ShellCheck
  run: |
    find . -name '*.sh' -not -path './.venv/*' -not -path './DerivedData/*' -exec shellcheck {} +
```

For repos that only contain shell scripts (none currently), shellcheck is the primary lint gate.

## Installing shellcheck

```bash
brew install shellcheck    # macOS
apt-get install shellcheck # Debian/Ubuntu
```
