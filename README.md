# punt-kit

> Standards, compliance tooling, and Claude Code plugin development patterns.

[![License](https://img.shields.io/github/license/punt-labs/punt-kit)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/punt-kit/test.yml?label=CI)](https://github.com/punt-labs/punt-kit/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/punt-kit)](https://pypi.org/project/punt-kit/)
[![Python](https://img.shields.io/pypi/pyversions/punt-kit)](https://pypi.org/project/punt-kit/)
[![Working Backwards](https://img.shields.io/badge/Working_Backwards-hypothesis-lightgrey)](./prfaq.pdf)

Punt-kit serves two purposes. For **Punt Labs projects**, it is the standards authority — coding conventions, CI templates, naming rules, and an audit checklist that the `punt` CLI enforces automatically. For **Claude Code plugin developers**, it is a pattern library — ten reusable design patterns extracted from shipping plugins, plus nine standards documents covering Python, CLI, shell, distribution, and more.

Individual projects reference these standards from their CLAUDE.md rather than duplicating them. The [standards/](standards/) directory is the source of truth; [patterns/](patterns/) documents the design patterns; [AGENTS.md](AGENTS.md) has the full audit checklist.

**Platforms:** macOS, Linux

## punt CLI

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/punt-kit/8a7f586/install.sh | sh
```

<details>
<summary>Manual install (if you already have uv)</summary>

```bash
uv tool install punt-kit
```

</details>

### Commands

| Command | What it does |
|---------|-------------|
| `punt init` | Scaffold a new Punt Labs project (CI, linter config, CLAUDE.md, permissions, beads) |
| `punt audit` | Check compliance against standards (read-only, no file changes) |
| `punt auto <target>` | Render and merge managed sections in project files (claude, makefile, settings). Supports `--dry-run` |
| `punt release [version]` | 11-phase release workflow (preflight → PyPI → cross-repo propagation). Supports `--resume-from` and `--dry-run` |
| `punt pii` | Scan repo for PII (emails, home paths, hostnames). Supports `--staged` for pre-commit |
| `punt doctor` | Check installation health (Python, uv, ruff, mypy, pyright) |
| `punt status` | Show detected project type, standards version, and beads state |
| `punt version` | Print version (`punt 0.8.0`) |

### Global Flags

All commands accept these flags:

| Flag | What it does |
|------|-------------|
| `--json` | Output as JSON (machine-readable) |
| `--verbose` / `-v` | Verbose output |
| `--quiet` / `-q` | Suppress non-essential output (errors only) |

### Usage

```bash
# In any Punt Labs project directory:
punt init          # Generate missing files
punt audit         # Check compliance
punt doctor        # Check installation health
punt status        # Show project summary
punt pii           # Scan for PII leaks
punt pii --staged  # Pre-commit: scan only staged files
punt --json status # JSON output for scripting
punt init /path    # Target a specific directory
```

`punt init` detects the project type (Python, Node.js, Swift, docs) and scaffolds everything a Punt Labs project needs to pass `punt audit`:

- **CI workflows** — lint, test, docs, and release workflows from Jinja2 templates
- **Python tool config** — `[tool.ruff]`, `[tool.mypy]`, `[tool.pyright]`, `[tool.pytest]` sections merged into `pyproject.toml`
- **CLAUDE.md** — standards references and quality gates tailored to the detected language
- **Claude Code permissions** — `.claude/settings.json` with tool allowlists and standard deny rules
- **Gitignore** — `.claude/` exceptions appended to `.gitignore`
- **Beads** — issue tracking initialized via `bd init`

After scaffolding, it reports manual steps that require GitHub access (branch protection rulesets, Copilot code review, Dependabot). Init is idempotent — re-running it updates existing files without overwriting customizations.

`punt audit` checks all standards without modifying files. It uses `gh api` to check GitHub-side settings when authenticated.

`punt pii` scans tracked files for personally identifiable information — email addresses, home directory paths (`/Users/X/`, `/home/X/`), and `.local` hostnames. Configure allow/deny lists in `[tool.punt.pii]` in `pyproject.toml`.

## Claude Code Plugin

Punt-kit is also a Claude Code plugin (`punt@punt-labs` on the marketplace). The plugin surfaces CLI commands as slash commands and adds LLM-driven capabilities that are inherently prompt-driven.

| Slash Command | What it does |
|---------------|-------------|
| `/punt:init` | Scaffold a Punt Labs project (wraps `punt init`) |
| `/punt:audit` | Check compliance (wraps `punt audit`) |
| `/punt:pii` | Scan for PII (wraps `punt pii`) |
| `/punt:auto <playbook>` | Execute automation playbooks (release, autopilot, standards-rollout) |
| `/punt:reconcile` | LLM-driven standards reconciliation (no CLI equivalent — prompt-driven) |
| `/punt:claude2cursor` | Generate Cursor skills and rules from plugin commands |

Install from the marketplace:

```text
/plugin install punt@punt-labs
```

---

## Standards

18 standards documents covering the full development lifecycle:

| Standard | Covers |
|----------|--------|
| [Python](standards/python.md) | ruff, mypy, pyright, pytest, pyproject.toml conventions |
| [CLI](standards/cli.md) | typer, `punt-` PyPI prefix, entry point naming, global flags |
| [Shell](standards/shell.md) | POSIX install scripts, bash dev scripts, shellcheck |
| [GitHub](standards/github.md) | Branch protection, PR workflow, Copilot review, Dependabot |
| [Workflow](standards/workflow.md) | Beads, branch discipline, micro-commits, session close |
| [Distribution](standards/distribution.md) | PyPI trusted publishing, `.mcpb` bundles, installers |
| [Plugins](standards/plugins.md) | Claude Code plugin structure, marketplace publishing |
| [Hooks](standards/hooks.md) | Claude Code hook events, three-layer dispatch pattern |
| [Permissions](standards/permissions.md) | Tool allowlists, deny rules, scope management |
| [Naming](standards/naming.md) | Package names, CLI commands, MCP tool prefixes |
| [Makefile](standards/makefile.md) | Required targets (check, lint, test, build, clean, depot) |
| [Logging](standards/logging.md) | Structured logging, log levels, stderr conventions |
| [Release Process](standards/release-process.md) | Versioning, changelog, tag workflow |
| [Node](standards/node.md) | Node.js MCP servers, `@modelcontextprotocol/sdk` |
| [README](standards/readme.md) | Badge set, section order, anti-patterns for project READMEs |

---

## Plugin Development Patterns

Ten design patterns extracted from shipping Claude Code plugins. Each pattern documents the problem, solution, trade-offs, and which projects use it.

| Pattern | What it solves |
|---------|---------------|
| [Two-Phase Install](patterns/two-phase-install.md) | `curl \| sh` bootstraps uv, then uv installs the package |
| [Dual Command Path](patterns/dual-command-path.md) | Dev commands use `uv run --directory`, prod commands use the installed CLI |
| [Two-Channel Display](patterns/two-channel-display.md) | Status bar for ambient state, conversation for interactions |
| [Stash and Wrap](patterns/stash-and-wrap.md) | PostToolUse hooks suppress raw MCP output, show clean narration |
| [Copy Not Symlink](patterns/copy-not-symlink.md) | Plugin install copies files instead of symlinking |
| [Doctor Checks](patterns/doctor-checks.md) | `doctor` command validates wiring (MCP, plugin, permissions) |
| [Prior Context Priming](patterns/prior-context-priming.md) | SessionStart hooks inject context that agents need immediately |
| [Dynamic Description Notify](patterns/dynamic-description-notify.md) | MCP tool descriptions change based on state |
| [Sibling PPID](patterns/sibling-ppid.md) | Detect whether a process is running inside Claude Code |
| [Design Decision Log](patterns/design-decision-log.md) | DESIGN.md with rejected alternatives and rationale |

---

## Projects Built With These Patterns

The standards and patterns above were extracted from shipping projects. Each has its own repo and README at [punt-labs](https://github.com/punt-labs).

- **[biff](https://github.com/punt-labs/biff)** — Team communication for the terminal (BSD Unix vocabulary over NATS)
- **[quarry](https://github.com/punt-labs/quarry)** — Local semantic search across 30+ document formats
- **[vox](https://github.com/punt-labs/vox)** — General-purpose TTS engine (ElevenLabs, OpenAI, Polly)
- **[ethos](https://github.com/punt-labs/ethos)** — Identity and persona management for Claude Code sessions
- **[beadle](https://github.com/punt-labs/beadle)** — Email client for Claude Code (Proton Bridge SMTP/IMAP)
- **[prfaq](https://github.com/punt-labs/prfaq)** — Working Backwards PR/FAQ generator (skill + 8 agents + 10 commands)
- **[z-spec](https://github.com/punt-labs/z-spec)** — Formal Z specifications for stateful systems
- **[dungeon](https://github.com/punt-labs/dungeon)** — Text adventure game (prompt-driven game engine)

---

## Development

```bash
uv sync                        # Install dependencies
uv run ruff check .            # Lint
uv run ruff format --check .   # Check formatting
uv run mypy src/ tests/        # Type check (mypy)
uv run pyright src/ tests/     # Type check (pyright)
uv run pytest                  # Test
```

## License

MIT
