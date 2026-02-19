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
- Use `"$(command)"` not bare `$(command)`.
- Shellcheck enforces this (SC2086, SC2046).

### Functions

- Define functions before calling them (SC2218).
- Use `local` for function-scoped variables.
- Prefer `snake_case` for function and variable names.

### Error handling

- `cd` must always have a fallback: `cd "$dir" || exit 1`.
- Check command existence before use: `command -v tool >/dev/null 2>&1 || { echo "tool not found"; exit 1; }`.
- Use `printf` over `echo` for portable output. Never use variables in `printf` format strings (SC2059).

### Style

- Indent with 2 spaces (consistent with Google Shell Style Guide).
- Max line length: 120 characters.
- Use `[[ ]]` for conditionals (not `[ ]`).
- Use `$(command)` for command substitution (not backticks).

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
    find . -name '*.sh' -not -path './.venv/*' -not -path './DerivedData/*' | xargs shellcheck
```

For repos that only contain shell scripts (none currently), shellcheck is the primary lint gate.

## Installing shellcheck

```bash
brew install shellcheck    # macOS
apt-get install shellcheck # Debian/Ubuntu
```
