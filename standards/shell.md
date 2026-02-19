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

Use `#!/usr/bin/env bash` — not `#!/bin/bash`, not `#!/bin/sh`.

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
