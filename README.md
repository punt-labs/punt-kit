# punt-kit

> Standards, compliance tooling, and Claude Code plugin development patterns.

[![License](https://img.shields.io/github/license/punt-labs/punt-kit)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/punt-kit/test.yml?label=CI)](https://github.com/punt-labs/punt-kit/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/punt-kit)](https://pypi.org/project/punt-kit/)
[![Python](https://img.shields.io/pypi/pyversions/punt-kit)](https://pypi.org/project/punt-kit/)
[![Working Backwards](https://img.shields.io/badge/Working_Backwards-hypothesis-lightgrey)](./prfaq.pdf)

punt-kit holds the engineering standards for Punt Labs projects and the `punt` CLI that applies them: `punt init` creates the files a project needs, and `punt audit` reports where a project differs from the standards. It also documents fourteen design patterns for Claude Code plugins, drawn from Punt Labs plugins, and standards for five languages (Python, Go, C, Swift, Pharo). A Claude Code plugin, `punt@punt-labs`, runs the CLI as slash commands.

Projects link to these standards from their `CLAUDE.md` (the instructions file Claude Code reads at the start of a session) instead of copying them. [standards/](standards/) holds the standards, [lang-rules/](lang-rules/) the per-language coding rules that Claude Code loads when it edits files in that language, [patterns/](patterns/) the design patterns, and [AGENTS.md](AGENTS.md) the full audit checklist.

**Platforms:** macOS, Linux

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/punt-kit/0740213/install.sh | sh
```

The installer installs [uv](https://docs.astral.sh/uv/) and Python 3.13 if they are missing, then installs the `punt-kit` package from PyPI, which provides the `punt` command. If the `claude` command is on your `PATH`, it also adds the `punt-labs` plugin marketplace to Claude Code and installs the `punt@punt-labs` plugin. It finishes by running `punt doctor`.

<details>
<summary>Manual install (if you already have uv)</summary>

Install the CLI:

```bash
uv tool install punt-kit
```

Add the Punt Labs marketplace to Claude Code:

```bash
claude plugin marketplace add punt-labs/claude-plugins
```

Install the plugin:

```bash
claude plugin install punt@punt-labs
```

</details>

<details>
<summary>Verify the install</summary>

```bash
punt doctor
```

`punt doctor` exits non-zero if Python 3.13 or later or `uv` is missing. It also reports whether `ruff`, `mypy`, and `pyright` are on your `PATH`, but their absence does not cause a failure.

</details>

## Commands

### Diagnostics and telemetry

Each `punt` invocation writes private diagnostics to
`~/.punt-labs/punt/logs/punt.log` (0700 directories, 0600 files); only warnings
and errors appear on stderr. Shared `punt-observe` handles redaction and rotation.
Local usage spans in `~/.punt-labs/punt/telemetry.db` contain only the closed
command name, outcome and JSON-output flag, never arguments, paths or content.
Set `PUNT_TELEMETRY=off` to disable capture entirely. Network export is not enabled.
The shared package is temporarily pinned to a Git commit, so source installation
requires Git and access to GitHub until it is available on PyPI.

### CLI

Each command that takes `[path]` runs on the current directory when the path is omitted.

| Command | What it does |
|---------|-------------|
| `punt init [path]` | Set up a Punt Labs project: CI workflows, linter config, `CLAUDE.md`, Claude Code permissions, and beads. `--language` overrides the detected language |
| `punt audit [path]` | Check the project against the standards. Read-only unless you pass `--fix` |
| `punt audit --fix [path]` | Also create missing files that need no judgment: markdownlint config, `py.typed`, and `CHANGELOG.md` |
| `punt enable [path]` | Enable punt in the repo: deposit its guide, add the `@.punt-labs/punt/CLAUDE.md` import, and allow `Skill(punt:*)`, with `ask` rules for `/punt:auto` and `/punt:reconcile` |
| `punt disable [path]` | Remove punt's import, `enabled` marker and permission rules. The guide stays in place, dormant |
| `punt seed <target> [path]` | Write or update the punt-managed sections of a project file. Targets: `makefile` (Python projects only) and `settings` (`.claude/settings.json`). `--dry-run` shows the changes without writing them |
| `punt release [version]` | Run the 11-phase release, from preflight checks through PyPI publishing to updates in sibling repositories. Supports `--resume-from <phase>`, `--dry-run`, and `--path` |
| `punt pii [path]` | Scan tracked files for personal information (email addresses, home directory paths, `.local` hostnames). `--staged` scans only staged files, for use in a pre-commit hook |
| `punt doctor` | Check the installation (Python, uv, ruff, mypy, pyright) |
| `punt status [path]` | Show the detected language and project type, whether the project is a plugin or MCP server, and its open and in-progress bead counts |
| `punt version` | Print the installed punt-kit version |

Beads is a local issue tracker with the `bd` command. `punt init` runs `bd init` when `bd` is on your `PATH` and skips that step otherwise.

### Global Flags

These flags go before the command name, for example `punt --json status`. `punt status --json` is an error.

| Flag | What it does |
|------|-------------|
| `--json` | Print machine-readable JSON |
| `--verbose` / `-v` | Print more detail |
| `--quiet` / `-q` | Print errors only |

### Slash Commands

The `punt@punt-labs` plugin adds these commands to Claude Code. The plugin does not include the `punt` program; the commands that call it need the CLI from the Quick Start.

| Slash Command | What it does |
|---------------|-------------|
| `/punt:init [path]` | Run `punt init` |
| `/punt:audit [path] [--fix]` | Run `punt audit` |
| `/punt:pii [path] [--staged]` | Run `punt pii` |
| `/punt:reconcile [path]` | Run `punt audit`, then have Claude compare the project's CI workflows, `CLAUDE.md`, and `pyproject.toml` with the standards and edit the parts that differ. Use it for changes that need judgment, which `punt audit --fix` does not make |
| `/punt:auto <playbook>` | Run an automation playbook: `release`, `autopilot`, `makefile`, `permissions-rollout`, `reconcile-memory`, or `standards-rollout` |
| `/punt:bead-review [repo]` | Review every open bead for clarity, validity, and priority, closing invalid ones and rewriting the rest. In a repository whose backlog has moved to Linear it stops and points you to Linear |

### What `punt init` Creates

`punt init` detects the project type (Python, Node.js, Go, Swift, or documentation only) and creates or updates:

- **CI workflows** — `docs.yml` for Markdown linting in every project; `lint.yml` and `test.yml` for Python; `lint.yml` for Node.js; `release.yml` for Python projects whose `pyproject.toml` names the package and its CLI command
- **Python tool config** — `[tool.ruff]`, `[tool.mypy]`, `[tool.pyright]`, and `[tool.pytest]` sections merged into `pyproject.toml`
- **CLAUDE.md** — links to the relevant standards and the quality-gate commands for the detected language
- **Claude Code permissions** — `.claude/settings.json` with the baseline allow list (`mcp__github__*`, the build and language tools, `Bash(bd:*)`, `Bash(punt:*)`, and `Bash(<cli>-server:*)` only when the project declares a `<cli>-server` entry point) and the standard deny rules. A plugin's MCP wildcard, its `Skill()` rules, and its own `Bash(<cli>:*)` rule are not added here; each tool's `enable` command adds them and its `disable` command removes them.
- **Gitignore** — a `.claude/` entry, with exceptions so `.claude/settings.json` and `.claude/hooks/` can still be committed
- **Beads** — issue tracking set up with `bd init`

It then lists the steps that need GitHub or dashboard access:

- **Branch protection** — the ruleset on `main`.
- **Review bots** ([PR and Review](standards/pr-review.md)):
  - copy the packaged `pr_agent.toml` template, at the path init prints, to `.pr_agent.toml`;
  - fill in its placeholders and merge it to `main`;
  - set Qodo's "Review every push" to Disable;
  - set Bugbot to review each PR once;
  - leave Copilot on request only, with no `copilot_code_review` ruleset rule.
- **Repository settings** — Dependabot, secret scanning, and automatic deletion of merged branches.

Running `punt init` again updates the files it manages without overwriting your own changes to them.

`punt audit` checks GitHub repository settings with the `gh` CLI when `gh` is installed and signed in. Its permissions check requires the baseline allow list and accepts entries added by each tool's `enable` command.

## Setup

### PII Scan Allow and Deny Lists

`punt pii` reads optional lists from a `[tool.punt.pii]` table in `pyproject.toml`: `allow_emails` (addresses that are not reported), `allow_patterns` (regular expressions for matches that are not reported), and `deny` (extra strings that are always reported). `--config <file>` reads the table from another file.

### Release Options

`punt release` installs the published package the way users install it, and can keep a Homebrew tap up to date. A project turns on each part:

| Option | Effect |
|--------|--------|
| `install-constraints.txt` at the repo root, exported from `uv.lock` | The verify install (Phase 8) reads it from the release tag and passes it as `uv tool install --constraints`. Without it the install is unpinned and the release says so. |
| `install-overrides.txt` at the repo root | Read from the release tag and passed as `--overrides`, so the verified environment matches the project's installer. |
| `[tool.punt-kit.release.service]` in `pyproject.toml`, with `systemd = "<unit>"` and/or `launchd = "<label>"` | After the verify install, the declared user service is restarted and must come back with a new PID. If the service manager cannot be queried, the release fails. If the service isn't loaded on this host, the release records a manual-action skip. |
| A `brew-formula` make target that honours `FORMULA_OUT=<path>`, plus `../homebrew-tap/Formula/<name>.rb` | Propagation (Phase 10) regenerates the formula, checks its version and archive URL name the release, adds a tap CHANGELOG entry, and opens the tap PR. Verify (Phase 11) checks the formula committed on the tap's `main`. |

## Standards

One document per topic. Each project's `CLAUDE.md` links to the ones it follows.

| Standard | Covers |
|----------|--------|
| [Standards and Rules](standards/standards.md) | How standards and language rules relate: clause IDs, rule citations and gates, no status, multi-language policy |
| [Architecture](standards/architecture.md) | The engine-and-clients model: one engine, thin library/CLI/MCP/REST client surfaces |
| [OO](standards/oo.md) | The object-oriented stance shared by Python, Swift, and Pharo |
| [Python](standards/python.md) | uv, ruff, mypy, pyright, pytest, the OO ratchet, pyproject.toml conventions |
| [Go](standards/go.md) | Idiomatic Go: modules, small interfaces, explicit errors, go vet + staticcheck |
| [C](standards/c.md) | Idiomatic C: memory ownership, `-Werror`, sanitizers |
| [Swift](standards/swift.md) | Idiomatic Swift realizing the OO stance |
| [Pharo](standards/pharo.md) | Pharo/Smalltalk, image-based development, in-image linting |
| [CLI](standards/cli.md) | typer, `punt-` PyPI prefix, entry point naming, global flags |
| [Shell](standards/shell.md) | POSIX install scripts, bash dev scripts, shellcheck |
| [CLI-Only Install](standards/install-cli-only.md) | `install.sh --no-plugin` / `<TOOL>_NO_PLUGIN=1`: install the CLI, skip the Claude Code plugin, identically across tools |
| [GitHub](standards/github.md) | Branch protection, PR workflow, review bots (Qodo, Bugbot), Dependabot |
| [CI](standards/ci.md) | What continuous integration must check before a merge, on every supported OS |
| [Workflow](standards/workflow.md) | The three-loop development structure (backlog / PR / mission), doorway conditions, gates, invariants |
| [PR and Review](standards/pr-review.md) | PR boundaries, the agent-owned review sequence, local review before remote, dismissal discipline |
| [Agent Engineering](standards/agent-engineering.md) | Operating rules for AI coding agents: reversibility, test coverage, comment discipline |
| [Context Management](standards/context-mgmt.md) | Lean, portable, drift-free agent config: don't duplicate what hooks inject or tools discover; index and disclose; one source generated per tool |
| [Git](standards/git.md) | Git mechanics: branch check, no-rewrite of pushed branches, conflict resolution, post-merge cleanup, worktrees, submodules |
| [Distribution](standards/distribution.md) | PyPI trusted publishing, `.mcpb` bundles, installers |
| [Plugins](standards/plugins.md) | Claude Code plugin structure, marketplace publishing |
| [Hooks](standards/hooks.md) | Claude Code hook events, three-layer dispatch pattern |
| [MCP Caller Identity](standards/mcp-caller-identity.md) | Which session and agent is calling: hook-stamped `_caller`, engine-owned sessions and handles, no identity on the connection |
| [Permissions](standards/permissions.md) | Tool allowlists, deny rules, scope management |
| [Filesystem](standards/filesystem.md) | `~/.punt-labs/<tool>/` home layout; reserved subdirectories; migration from legacy dot-directories |
| [Tool Enable/Disable](standards/tool-enable-disable.md) | One @-import per enabled tool; zoned `.punt-labs/<tool>/` subtree (vendored zone tool-owned); enable/disable verbs; required user-guide doc |
| [Repo-Local State Directory](standards/punt-labs-dir.md) | `<repo>/.punt-labs/<tool>/` tool roots plus the machine-local `.punt-labs/local/` zone; committed except local-convention paths (`local/`, `*.local`, `*.local.*`); live state never tracked (seal pattern, chunk-based); canonical gitignore block; subtree zones |
| [Naming](standards/naming.md) | Package names, CLI commands, MCP tool prefixes |
| [Makefile](standards/makefile.md) | Required targets (check, lint, test, build, clean) and the optional `depot` target |
| [Logging](standards/logging.md) | Language-neutral diagnostic policy: private files, multi-process-safe rotation, redaction; [Python rules](lang-rules/python/python-logging.md) |
| [Telemetry](standards/telemetry.md) | Language-neutral OTel policy: privacy-safe schemas, local SQLite, retention, opt-in export; [Python rules](lang-rules/python/python-logging.md) |
| [Release Process](standards/release-process.md) | Versioning, changelog, tag workflow |
| [Release Requirements](standards/release-requirements.md) | End-state artifacts every release must satisfy, in the originating repo and siblings |
| [Integration](standards/integration.md) | How tools discover and coordinate each other in a session without hard dependencies |
| [README](standards/readme.md) | Audience, badge set, section order, tone, anti-patterns for project READMEs |

## Development Quality Gates

For this checkout, `uv sync` installs the PyPI
[`punt-oo-ratchet`](https://pypi.org/project/punt-oo-ratchet/) dev package.
`make check` includes OO, coupling/cohesion, and suppression-count ratchets;
`make report` shows per-file OO metrics. See the
[adoption rule](lang-rules/python/python-oo-adoption.md) for baseline updates
and CI wiring.

## Plugin Development Patterns

Fourteen design patterns drawn from Punt Labs Claude Code plugins. Each one describes the problem, the solution, the trade-offs, and which projects use it.

| Pattern | What it solves |
|---------|---------------|
| [Two-Phase Install](patterns/two-phase-install.md) | `uv tool install` cannot run the `claude` CLI, so the package install and the Claude Code setup are separate steps |
| [CLAUDE.md @-import Includes](patterns/claude-md-import-includes.md) | Each tool owns its usage doc; the project's `CLAUDE.md` holds one bare `@`-import line and no tool-managed text |
| [Daemon + Proxy MCP](patterns/daemon-proxy-mcp.md) | A long-running daemon behind an MCP proxy, for tools that are slow to start |
| [Humble Object Commands](patterns/humble-object-commands.md) | CLI commands as thin shells over testable core calls — no infrastructure in `@app.command()` bodies |
| [Ethos Extension Setup](patterns/ethos-ext-setup.md) | Tools write session context into ethos identity extension files during install |
| [Dual Command Path](patterns/dual-command-path.md) | Short top-level commands (`/who`) alongside the plugin's namespaced ones (`/biff:who`) |
| [Two-Channel Display](patterns/two-channel-display.md) | A one-line summary in the tool-result panel, with the full output passed to the model to print |
| [Stash and Wrap](patterns/stash-and-wrap.md) | Add a segment to Claude Code's single status line command without losing the user's existing one |
| [Copy Not Symlink](patterns/copy-not-symlink.md) | Copy top-level commands into `~/.claude/commands/` instead of symlinking into the plugin cache |
| [Doctor Checks](patterns/doctor-checks.md) | A `doctor` command that checks the installation, with required and informational checks |
| [Prior Context Priming](patterns/prior-context-priming.md) | Deliver formatting guidance through the MCP server's `instructions` field, before any tool call |
| [Dynamic Description Notify](patterns/dynamic-description-notify.md) | Change an MCP tool's description to show new state, then send `tools/list_changed` |
| [Homebrew Formula for a PyPI CLI](patterns/homebrew-pypi-formula.md) | Ship a PyPI-published Python CLI through the Homebrew tap with every dependency declared |
| [Design Decision Log](patterns/design-decision-log.md) | DESIGN.md with rejected alternatives and rationale |

## Documentation

[Contributing](CONTRIBUTING.md) |
[Plugin Development](docs/development.md) |
[Design Decisions](DESIGN.md) |
[PR/FAQ](prfaq.pdf) |
[Changelog](CHANGELOG.md)

## License

MIT
