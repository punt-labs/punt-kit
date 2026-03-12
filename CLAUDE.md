# Agent Instructions

This project follows [Punt Labs standards](https://github.com/punt-labs/punt-kit).

## No "Pre-existing" Excuse

There is no such thing as a "pre-existing" issue. If you see a problem — in code you wrote, code a reviewer flagged, or code you happen to be reading — you fix it. Do not classify issues as "pre-existing" to justify ignoring them. Do not suggest that something is "outside the scope of this change." If it is broken and you can see it, it is your problem now.

## Scratch Files

Use `.tmp/` at the project root for scratch and temporary files — never `/tmp`. The `TMPDIR` environment variable is set via `.envrc` so that `tempfile` and subprocesses automatically use it. Contents are gitignored; only `.gitkeep` is tracked.

## Quality Gates

Run before every commit. Zero violations, zero errors, all tests green.

```bash
make check
```

The Makefile is the source of truth for what `check` means (`make help` lists targets).

## Beads: Dual Role

punt-kit `.beads/` tracks **both** project-specific work (punt-kit tooling, standards doc updates) and **org-wide** cross-project work (CI rollouts, security enablement, multi-repo changes). See the [parent CLAUDE.md](../CLAUDE.md#where-to-create-a-bead) for the full placement scheme.

## Plugin Lifecycle

punt-kit is both a Python package (`punt` CLI) and a Claude Code plugin
(`punt@punt-labs` on the marketplace). The plugin wraps the CLI with slash
commands (`/punt init`, `/punt audit`, `/punt reconcile`, `/punt claude2cursor`, etc.).

### Key rules

- **Never hand-edit plugin JSON config files** (`installed_plugins.json`,
  `enabledPlugins`, cache dirs). Use `claude plugin` CLI commands or the
  `/plugin` slash command instead.
- **Plugin changes require a publish cycle**: bump version in `plugin.json` →
  push → update marketplace catalog (`punt-labs/claude-plugins`) → user runs
  `/plugin update`.
- **Dev/prod isolation**: the working tree uses `name: "punt-dev"` so
  developers see both `punt:*` (marketplace) and `punt-dev:*` (local) commands
  side by side. Launch with `claude --plugin-dir .` from the repo root.
- **Can't run `claude` inside a session** — ask the user to run plugin CLI
  commands in a separate terminal when needed.
- **`/punt claude2cursor [path]`** — Write Cursor skills (and optional rules) from this plugin's commands into the workspace or the given path. Safe to run repeatedly; overwrites and cleans up obsolete artifacts.

### Developer launch

```bash
claude --plugin-dir .                       # Load local plugin alongside marketplace
```

### Marketplace publish flow

1. Bump `version` in `.claude-plugin/plugin.json`
2. Push to main
3. Update `punt-labs/claude-plugins` marketplace catalog (version + description)
4. Users pick up changes via `/plugin update`

## Claude Code CLI Reference

All `claude` subcommands below must be run from a **separate terminal** — they
cannot be invoked from within a Claude Code session.

### Plugin management (`claude plugin`)

```bash
claude plugin list [--json] [--available]        # List installed plugins
claude plugin install <name>@<marketplace> [-s user|project|local]
claude plugin uninstall <name>@<marketplace> [-s user|project|local]
claude plugin enable <name>@<marketplace> [-s user|project|local]
claude plugin disable <name>@<marketplace> [-s user|project|local]
claude plugin disable --all                      # Disable everything
claude plugin update <name>@<marketplace> [-s user|project|local|managed]
claude plugin validate <path>                    # Validate plugin structure
```

Marketplace management:

```bash
claude plugin marketplace list [--json]
claude plugin marketplace add <source>           # GitHub owner/repo, git URL, or local path
claude plugin marketplace remove <name>
claude plugin marketplace update [name]          # Update one or all marketplaces
```

Scope options: `user` (default, `~/.claude/settings.json`), `project`
(`.claude/settings.json`, version-controlled), `local`
(`.claude/settings.local.json`, gitignored).

### MCP server management (`claude mcp`)

```bash
claude mcp list                                  # List all configured MCP servers
claude mcp get <name>                            # Details for one server
claude mcp add [-t stdio|sse|http] [-s local|user|project] [-e KEY=val] <name> <cmd> [args...]
claude mcp add-json <name> '<json>' [-s scope]   # Add from JSON config
claude mcp remove <name> [-s scope]
claude mcp reset-project-choices                 # Reset .mcp.json approvals
claude mcp serve [-d]                            # Run Claude Code as an MCP server
```

### Authentication (`claude auth`)

```bash
claude auth login [--email <email>] [--sso]
claude auth logout
claude auth status [--json|--text]
```

### Other commands

```bash
claude agents [--setting-sources user,project,local]  # List configured agents
claude doctor                                    # Health check (MCP, plugins, updates)
claude update                                    # Check for and install updates
claude install [stable|latest|<version>]         # Install native build
claude setup-token                               # Set up long-lived auth token
```

### Key top-level flags

| Flag | Description |
|------|-------------|
| `--plugin-dir <path>` | Load plugin from directory (session-only, repeatable) |
| `--model <model>` | Model: `sonnet`, `opus`, or full ID |
| `-c, --continue` | Continue most recent conversation |
| `-r, --resume [id]` | Resume a session by ID or picker |
| `-p, --print` | Non-interactive mode (SDK/scripting) |
| `-w, --worktree [name]` | Start in isolated git worktree |
| `--mcp-config <path>` | Load MCP servers from JSON file |
| `--allowedTools <tools>` | Auto-allow specific tools |
| `--disallowedTools <tools>` | Remove tools from context |
| `--add-dir <dirs>` | Add working directories |
| `--system-prompt <text>` | Replace system prompt (print mode) |
| `--append-system-prompt <text>` | Append to system prompt |
| `--max-turns <n>` | Limit agentic turns (print mode) |
| `--output-format <fmt>` | Output: `text`, `json`, `stream-json` |

### Interactive slash commands (inside a session)

These are available within a running Claude Code session, not from the shell:

| Command | Description |
|---------|-------------|
| `/plugin` | Browse, install, enable, disable plugins |
| `/mcp` | View and manage MCP servers |
| `/config` | Open settings interface |
| `/model` | Switch model |
| `/permissions` | Manage permission rules |
| `/doctor` | Diagnose issues |
| `/compact` | Compact conversation context |

## Release Workflow

`punt release` handles phases 1–9: preflight, version bump, build, tag/push,
CI wait, GitHub release, PyPI verify, cross-repo propagation, and verification.

### Key assumptions

- **Sibling repos checked out**: Phase 8 (propagation) requires `../punt-kit`,
  `../claude-plugins`, and `../.github` to be checked out as siblings in the
  same parent directory, on `main`, with clean working trees. `../public-website`
  is optional (skipped if absent).
- **Push access to siblings**: The developer's SSH/HTTPS credential must allow
  `git push origin main` on all required siblings.
- **PyPI approval gate**: The `pypi` job in the release workflow requires
  manual approval in the GitHub Actions UI. Phase 5 (CI wait) blocks until
  all jobs complete, so the developer must approve the deployment during the
  release. Expect ~20 minutes for the full pipeline (build → TestPyPI →
  test-install → approve → PyPI).
- **`--resume-from <phase>`**: Resumes from any phase. When resuming without an
  explicit version, reads from `pyproject.toml` (not changelog). Always pass the
  version explicitly when resuming from `bump` if Phase 2 hasn't completed.

See [DESIGN.md](DESIGN.md) DES-013 and DES-014 for the full rationale.

## Pre-PR Checklist

- [ ] **CHANGELOG entry included in the PR diff** under `## [Unreleased]` (not retroactively on main)
- [ ] **README updated** if user-facing behavior changed (new flags, commands, defaults, config)
- [ ] **prfaq.tex updated** if the change shifts product direction or validates/invalidates a risk
- [ ] **Quality gates pass** — `make check`

## Code Review

See [Workflow standards §8](standards/workflow.md) for the full specification. Key rules inlined here:

1. **Create PR** via `mcp__github__create_pull_request`. Prefer MCP GitHub tools over `gh` CLI where possible.
2. **Request Copilot review** via `mcp__github__request_copilot_review`.
3. **Watch for CI/Copilot/Bugbot feedback without blocking your main shell** — run `gh pr checks <number> --watch` in a background task or separate session. Do not stop waiting. Copilot and Bugbot may take 1–3 minutes to post after CI completes. Do not assume silence means approval.
4. **Read all feedback** using MCP tools:
   - `mcp__github__pull_request_read` with `get_reviews` — check review verdicts
   - `mcp__github__pull_request_read` with `get_review_comments` — read inline comments
5. **Take every comment seriously.** If a reviewer flags it, you fix it. There is no such thing as "pre-existing" or "unrelated to this change" — if you can see it, you own it. If you genuinely disagree, explain why in a reply — do not silently ignore.
6. **Fix, re-push, repeat.** Each fix commit triggers a new review cycle. Expect **2–6 review cycles** before merging.
7. **Merge only when the last review cycle is uneventful** — zero new comments, all checks green. Use `mcp__github__merge_pull_request` (not `gh pr merge`, which has local side effects).

## Design Decisions

Consult [DESIGN.md](DESIGN.md) before proposing changes to settled
architecture. Log new decisions there when they involve rejected alternatives.

## Standards References

- [Python](https://github.com/punt-labs/punt-kit/blob/main/standards/python.md)
- [GitHub](https://github.com/punt-labs/punt-kit/blob/main/standards/github.md)
- [Workflow](https://github.com/punt-labs/punt-kit/blob/main/standards/workflow.md)
- [CLI](https://github.com/punt-labs/punt-kit/blob/main/standards/cli.md)
- [Shell](https://github.com/punt-labs/punt-kit/blob/main/standards/shell.md)
